"""Base entities and device-registry helpers for evohome_enhanced."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, override

import evohomeasync2 as evo
from evohomeasync2.const import ZoneModelType, ZoneType
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, MANUFACTURER
from .coordinator import EvoDataUpdateCoordinator
from .logic import zone_unique_id

_LOGGER = logging.getLogger(__name__)

type EvoDevice = evo.ControlSystem | evo.HotWater | evo.Zone


def is_valid_zone(zone: evo.Zone) -> bool:
    """Return True if a zone should be exposed as entities."""
    return zone.model == ZoneModelType.HEATING_ZONE or zone.type == ZoneType.THERMOSTAT


def evo_uid(device: EvoDevice) -> str:
    """Return the stable unique-id stem for any evohome device."""
    if isinstance(device, evo.Zone):
        return zone_unique_id(device.id, device.tcs.id)
    return device.id


def unique_zone_id(zone: evo.Zone) -> str:
    """Return a collision-free unique id for a zone."""
    return zone_unique_id(zone.id, zone.tcs.id)


def evo_device_info(
    coordinator: EvoDataUpdateCoordinator, device: EvoDevice
) -> DeviceInfo:
    """Build the device-registry entry, linking children to the controller."""
    if isinstance(device, evo.ControlSystem):
        return DeviceInfo(
            identifiers={(DOMAIN, device.id)},
            manufacturer=MANUFACTURER,
            model=str(device.model),
            name=device.location.name,
        )
    return DeviceInfo(
        identifiers={(DOMAIN, evo_uid(device))},
        manufacturer=MANUFACTURER,
        model=str(getattr(device, "model", "") or "") or None,
        name=device.name,
        via_device=(DOMAIN, coordinator.tcs.id),
    )


class EvoEntity(CoordinatorEntity[EvoDataUpdateCoordinator]):
    """Base for Evohome's climate & water-heater entities."""

    _evo_device: EvoDevice
    _evo_id_attr: str
    _evo_state_attr_names: tuple[str, ...]

    def __init__(
        self, coordinator: EvoDataUpdateCoordinator, evo_device: EvoDevice
    ) -> None:
        """Initialise an evohome entity (controller, DHW or zone)."""
        super().__init__(coordinator, context=evo_device.id)
        self._evo_device = evo_device
        self._attr_device_info = evo_device_info(coordinator, evo_device)
        self._device_state_attrs: dict[str, Any] = {}

    @property
    @override
    def extra_state_attributes(self) -> Mapping[str, Any]:
        """Return the evohome-specific state attributes."""
        return {"status": self._device_state_attrs}

    @callback
    @override
    def _handle_coordinator_update(self) -> None:
        self._device_state_attrs[self._evo_id_attr] = self._evo_device.id
        for attr in self._evo_state_attr_names:
            self._device_state_attrs[attr] = getattr(self._evo_device, attr)
        super()._handle_coordinator_update()

    async def update_attrs(self) -> None:
        """Refresh the entity's extra state attributes."""
        self._handle_coordinator_update()


class EvoChild(EvoEntity):
    """Base for any evohome child entity (a zone or the DHW controller)."""

    _evo_device: evo.HotWater | evo.Zone

    def __init__(
        self,
        coordinator: EvoDataUpdateCoordinator,
        evo_device: evo.HotWater | evo.Zone,
    ) -> None:
        """Initialise an evohome child entity."""
        super().__init__(coordinator, evo_device)
        self._evo_id = evo_device.id
        self._evo_tcs = evo_device.tcs
        self._schedule: Any | None = None
        self._setpoints: dict[str, Any] = {}

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature, preferring high-precision values."""
        if (temp := self.coordinator.temps.get(self._evo_id)) is not None:
            return temp
        return self._evo_device.temperature

    @property
    def setpoints(self) -> Mapping[str, Any]:
        """Return the current/next switchpoints from the schedule."""
        if not self._schedule:
            return self._setpoints

        this_sp_dtm, this_sp_val = self._evo_device.this_switchpoint
        next_sp_dtm, next_sp_val = self._evo_device.next_switchpoint
        key = "temp" if isinstance(self._evo_device, evo.Zone) else "state"

        self._setpoints = {
            "this_sp_from": this_sp_dtm,
            f"this_sp_{key}": this_sp_val,
            "next_sp_from": next_sp_dtm,
            f"next_sp_{key}": next_sp_val,
        }
        return self._setpoints

    async def _update_schedule(self, force_refresh: bool = False) -> None:
        """Refresh the device schedule if stale (or forced)."""
        next_from = self._setpoints.get("next_sp_from")
        if not (
            force_refresh
            or self._schedule is None
            or (next_from is not None and next_from < dt_util.utcnow())
        ):
            _ = self.setpoints
            return

        try:
            self._schedule = await self.coordinator.call_client_api(
                self._evo_device.get_schedule(),  # type: ignore[arg-type]
                request_refresh=False,
            )  # type: ignore[assignment]
        except evo.InvalidScheduleError as err:
            _LOGGER.warning("%s: invalid schedule: %s", self._evo_device, err)
            self._schedule = []

        _ = self.setpoints  # refresh the cached setpoints attr

    @callback
    @override
    def _handle_coordinator_update(self) -> None:
        self._device_state_attrs = {
            "activeFaults": self._evo_device.active_faults,
            "setpoints": self.setpoints,
        }
        super()._handle_coordinator_update()

    @override
    async def update_attrs(self) -> None:
        await self._update_schedule()
        await super().update_attrs()


class EvoDescriptorEntity(CoordinatorEntity[EvoDataUpdateCoordinator]):
    """Base for description-driven entities (sensor, binary_sensor).

    These are read-only projections of coordinator data and attach to the same
    device-registry device as their parent climate/water-heater entity.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: EvoDataUpdateCoordinator,
        device: EvoDevice,
        description: EntityDescription,
    ) -> None:
        """Initialise a description-driven entity."""
        super().__init__(coordinator, context=device.id)
        self._evo_device = device
        self.entity_description = description
        self._attr_unique_id = f"{evo_uid(device)}_{description.key}"
        self._attr_device_info = evo_device_info(coordinator, device)
