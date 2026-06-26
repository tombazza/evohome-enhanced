"""Water heater platform for evohome_enhanced (DHW controller)."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any, override

import evohomeasync2 as evo
import voluptuous as vol
from evohomeasync2.const import SZ_STATE_STATUS, SZ_TEMPERATURE_STATUS
from evohomeasync2.schemas.const import DhwState as EvoDhwState
from evohomeasync2.schemas.const import ZoneMode as EvoZoneMode
from homeassistant.components.water_heater import (
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.const import (
    ATTR_STATE,
    PRECISION_TENTHS,
    PRECISION_WHOLE,
    STATE_OFF,
    STATE_ON,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.util import dt as dt_util

from .const import ATTR_DURATION, EvoService
from .coordinator import EvoDataUpdateCoordinator
from .entity import EvoChild

if TYPE_CHECKING:
    from . import EvoConfigEntry

STATE_AUTO = "auto"

HA_STATE_TO_EVO = {STATE_AUTO: "", STATE_ON: EvoDhwState.ON, STATE_OFF: EvoDhwState.OFF}
EVO_STATE_TO_HA = {v: k for k, v in HA_STATE_TO_EVO.items() if k != ""}

SET_DHW_OVERRIDE_SCHEMA = {
    vol.Required(ATTR_STATE): cv.boolean,
    vol.Optional(ATTR_DURATION): vol.All(
        cv.time_period, vol.Range(min=timedelta(days=0), max=timedelta(days=1))
    ),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EvoConfigEntry,
    async_add_entities: entity_platform.AddEntitiesCallback,
) -> None:
    """Set up the DHW water heater, if present."""
    coordinator = entry.runtime_data.coordinator
    dhw = entry.runtime_data.tcs.hotwater
    if dhw is None:
        return

    entity = EvoDHW(coordinator, dhw)
    async_add_entities([entity])
    await entity.update_attrs()

    entity_platform.async_get_current_platform().async_register_entity_service(
        EvoService.SET_DHW_OVERRIDE, SET_DHW_OVERRIDE_SCHEMA, "async_set_dhw_override"
    )


class EvoDHW(EvoChild, WaterHeaterEntity):
    """An evohome DHW (domestic hot water) controller."""

    _attr_operation_list = list(HA_STATE_TO_EVO)
    _attr_supported_features = (
        WaterHeaterEntityFeature.AWAY_MODE
        | WaterHeaterEntityFeature.ON_OFF
        | WaterHeaterEntityFeature.OPERATION_MODE
    )
    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    _evo_device: evo.HotWater
    _evo_id_attr = "dhw_id"
    _evo_state_attr_names = (SZ_STATE_STATUS, SZ_TEMPERATURE_STATUS)

    def __init__(
        self, coordinator: EvoDataUpdateCoordinator, evo_device: evo.HotWater
    ) -> None:
        """Initialise a DHW controller."""
        super().__init__(coordinator, evo_device)

        self._attr_unique_id = evo_device.id
        self._attr_name = evo_device.name
        self._attr_precision = (
            PRECISION_TENTHS if coordinator.client_v1 else PRECISION_WHOLE
        )

    async def async_set_dhw_override(
        self, state: bool, duration: timedelta | None = None
    ) -> None:
        """Override the DHW on/off state, permanently or for a duration."""
        if duration is None:
            until = None
        elif duration.total_seconds() == 0:
            await self._update_schedule()
            until = self.setpoints.get("next_sp_from")
        else:
            until = dt_util.now() + duration

        until = dt_util.as_utc(until) if until else None
        api = self._evo_device.set_on if state else self._evo_device.set_off
        await self.coordinator.call_client_api(api(until=until))

    @property
    @override
    def current_operation(self) -> str | None:
        """Return the current operating mode (auto, on, off)."""
        if self._evo_device.mode == EvoZoneMode.FOLLOW_SCHEDULE:
            return STATE_AUTO
        return EVO_STATE_TO_HA[self._evo_device.state]

    @property
    @override
    def is_away_mode_on(self) -> bool:
        """Return True if away mode is on (permanently off)."""
        is_off = EVO_STATE_TO_HA[self._evo_device.state] == STATE_OFF
        return is_off and self._evo_device.mode == EvoZoneMode.PERMANENT_OVERRIDE

    @override
    async def async_set_operation_mode(self, operation_mode: str) -> None:
        """Set the operation mode (auto follows schedule; else until next setpoint)."""
        if operation_mode == STATE_AUTO:
            await self.coordinator.call_client_api(self._evo_device.reset())
            return

        await self._update_schedule()
        until = self.setpoints.get("next_sp_from")
        until = dt_util.as_utc(until) if until else None
        on = operation_mode == STATE_ON
        api = self._evo_device.set_on if on else self._evo_device.set_off
        await self.coordinator.call_client_api(api(until=until))

    @override
    async def async_turn_away_mode_on(self) -> None:
        """Turn away mode on."""
        await self.coordinator.call_client_api(self._evo_device.set_off())

    @override
    async def async_turn_away_mode_off(self) -> None:
        """Turn away mode off."""
        await self.coordinator.call_client_api(self._evo_device.reset())

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on."""
        await self.coordinator.call_client_api(self._evo_device.set_on())

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off."""
        await self.coordinator.call_client_api(self._evo_device.set_off())
