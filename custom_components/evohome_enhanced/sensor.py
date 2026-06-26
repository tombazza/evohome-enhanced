"""Sensor platform for evohome_enhanced.

Surfaces data that the official integration buries inside climate attributes as
first-class sensors, so it can drive sensor cards, graphs and long-term
statistics.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from .coordinator import EvoDataUpdateCoordinator
from .entity import EvoDescriptorEntity, is_valid_zone
from .logic import heat_demand_pct, precise_temperature

if TYPE_CHECKING:
    from . import EvoConfigEntry


def _status(device: Any) -> dict[str, Any] | None:
    """Return a device's status dict, or None if not yet available."""
    try:
        return device.status
    except Exception:
        return None


def _temperature(device: Any, coordinator: EvoDataUpdateCoordinator) -> StateType:
    return precise_temperature(coordinator.temps.get(device.id), device.temperature)


@dataclass(frozen=True, kw_only=True)
class EvoSensorDescription(SensorEntityDescription):
    """Describes an Evohome sensor."""

    value_fn: Callable[[Any, EvoDataUpdateCoordinator], StateType]
    exists_fn: Callable[[Any], bool] = lambda _device: True


_TEMPERATURE = {
    "device_class": SensorDeviceClass.TEMPERATURE,
    "state_class": SensorStateClass.MEASUREMENT,
    "native_unit_of_measurement": UnitOfTemperature.CELSIUS,
}
_HEAT_DEMAND = {
    "translation_key": "heat_demand",
    "native_unit_of_measurement": PERCENTAGE,
    "state_class": SensorStateClass.MEASUREMENT,
    "entity_category": EntityCategory.DIAGNOSTIC,
    "value_fn": lambda d, _c: heat_demand_pct(_status(d)),
    "exists_fn": lambda d: heat_demand_pct(_status(d)) is not None,
}

ZONE_SENSORS: tuple[EvoSensorDescription, ...] = (
    EvoSensorDescription(key="temperature", value_fn=_temperature, **_TEMPERATURE),
    EvoSensorDescription(
        key="setpoint",
        translation_key="setpoint",
        value_fn=lambda z, _c: z.target_heat_temperature,
        **_TEMPERATURE,
    ),
    EvoSensorDescription(key="heat_demand", **_HEAT_DEMAND),
    EvoSensorDescription(
        key="mode",
        translation_key="zone_mode",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda z, _c: str(z.mode) if z.mode else None,
    ),
)

DHW_SENSORS: tuple[EvoSensorDescription, ...] = (
    EvoSensorDescription(key="temperature", value_fn=_temperature, **_TEMPERATURE),
    EvoSensorDescription(key="heat_demand", **_HEAT_DEMAND),
)

TCS_SENSORS: tuple[EvoSensorDescription, ...] = (
    EvoSensorDescription(
        key="system_mode",
        translation_key="system_mode",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda t, _c: str(t.mode) if t.mode else None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EvoConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Evohome sensors from a config entry."""
    coordinator = entry.runtime_data.coordinator
    tcs = entry.runtime_data.tcs

    entities: list[EvoSensor] = [
        EvoSensor(coordinator, zone, desc)
        for zone in tcs.zones
        if is_valid_zone(zone)
        for desc in ZONE_SENSORS
        if desc.exists_fn(zone)
    ]
    entities += [EvoSensor(coordinator, tcs, desc) for desc in TCS_SENSORS]
    if tcs.hotwater:
        entities += [
            EvoSensor(coordinator, tcs.hotwater, desc)
            for desc in DHW_SENSORS
            if desc.exists_fn(tcs.hotwater)
        ]

    async_add_entities(entities)


class EvoSensor(EvoDescriptorEntity, SensorEntity):
    """A read-only Evohome sensor."""

    entity_description: EvoSensorDescription

    @property
    def native_value(self) -> StateType:
        """Return the sensor's current value."""
        return self.entity_description.value_fn(self._evo_device, self.coordinator)
