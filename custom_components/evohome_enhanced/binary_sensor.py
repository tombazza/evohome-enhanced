"""Binary sensor platform for evohome_enhanced.

Exposes fault state, heat demand and DHW activity as proper binary sensors
instead of opaque climate attributes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from evohomeasync2.schemas.const import DhwState as EvoDhwState
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import EvoDataUpdateCoordinator
from .entity import EvoDescriptorEntity, is_valid_zone
from .logic import calling_for_heat, has_active_fault, heat_demand_pct

if TYPE_CHECKING:
    from . import EvoConfigEntry


def _status(device: Any) -> dict[str, Any] | None:
    try:
        return device.status
    except Exception:
        return None


@dataclass(frozen=True, kw_only=True)
class EvoBinarySensorDescription(BinarySensorEntityDescription):
    """Describes an Evohome binary sensor."""

    value_fn: Callable[[Any, EvoDataUpdateCoordinator], bool | None]
    exists_fn: Callable[[Any], bool] = lambda _device: True


_FAULT = EvoBinarySensorDescription(
    key="fault",
    translation_key="fault",
    device_class=BinarySensorDeviceClass.PROBLEM,
    entity_category=EntityCategory.DIAGNOSTIC,
    value_fn=lambda d, _c: has_active_fault(d.active_faults),
)
_CALLING_FOR_HEAT = EvoBinarySensorDescription(
    key="calling_for_heat",
    translation_key="calling_for_heat",
    device_class=BinarySensorDeviceClass.HEAT,
    value_fn=lambda d, _c: calling_for_heat(_status(d)),
    exists_fn=lambda d: heat_demand_pct(_status(d)) is not None,
)

ZONE_BINARY_SENSORS = (_FAULT, _CALLING_FOR_HEAT)

DHW_BINARY_SENSORS = (
    _FAULT,
    EvoBinarySensorDescription(
        key="heating",
        translation_key="dhw_heating",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda d, _c: d.state == EvoDhwState.ON,
    ),
)

TCS_BINARY_SENSORS = (
    EvoBinarySensorDescription(
        key="fault",
        translation_key="fault",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda t, _c: has_active_fault(
            t.active_faults, t.gateway.active_faults
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EvoConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Evohome binary sensors from a config entry."""
    coordinator = entry.runtime_data.coordinator
    tcs = entry.runtime_data.tcs

    entities: list[EvoBinarySensor] = [
        EvoBinarySensor(coordinator, zone, desc)
        for zone in tcs.zones
        if is_valid_zone(zone)
        for desc in ZONE_BINARY_SENSORS
        if desc.exists_fn(zone)
    ]
    entities += [EvoBinarySensor(coordinator, tcs, desc) for desc in TCS_BINARY_SENSORS]
    if tcs.hotwater:
        entities += [
            EvoBinarySensor(coordinator, tcs.hotwater, desc)
            for desc in DHW_BINARY_SENSORS
            if desc.exists_fn(tcs.hotwater)
        ]

    async_add_entities(entities)


class EvoBinarySensor(EvoDescriptorEntity, BinarySensorEntity):
    """A read-only Evohome binary sensor."""

    entity_description: EvoBinarySensorDescription

    @property
    def is_on(self) -> bool | None:
        """Return whether the binary sensor is on."""
        return self.entity_description.value_fn(self._evo_device, self.coordinator)
