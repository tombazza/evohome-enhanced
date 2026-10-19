"""Climate platform for evohome_enhanced (controller + heating zones)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, override

import evohomeasync2 as evo
import voluptuous as vol
from evohomeasync2.const import (
    SZ_SETPOINT_STATUS,
    SZ_SYSTEM_MODE,
    SZ_SYSTEM_MODE_STATUS,
    SZ_TEMPERATURE_STATUS,
)
from evohomeasync2.const import SystemMode as EvoSystemMode
from evohomeasync2.const import ZoneMode as EvoZoneMode
from homeassistant.components.climate import (
    PRESET_AWAY,
    PRESET_ECO,
    PRESET_HOME,
    PRESET_NONE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import (
    ATTR_MODE,
    ATTR_TEMPERATURE,
    PRECISION_TENTHS,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.util import dt as dt_util

from .const import ATTR_DURATION, ATTR_PERIOD, ATTR_SETPOINT, DOMAIN, EvoService
from .coordinator import EvoDataUpdateCoordinator
from .entity import EvoChild, EvoEntity, is_valid_zone, unique_zone_id

if TYPE_CHECKING:
    from . import EvoConfigEntry

_LOGGER = logging.getLogger(__name__)

PRESET_CUSTOM = "Custom"
PRESET_RESET = "Reset"

TCS_PRESET_TO_HA = {
    EvoSystemMode.AWAY: PRESET_AWAY,
    EvoSystemMode.CUSTOM: PRESET_CUSTOM,
    EvoSystemMode.AUTO_WITH_ECO: PRESET_ECO,
    EvoSystemMode.DAY_OFF: PRESET_HOME,
    EvoSystemMode.AUTO_WITH_RESET: PRESET_RESET,
}
HA_PRESET_TO_TCS = {v: k for k, v in TCS_PRESET_TO_HA.items()}

EVO_PRESET_TO_HA = {
    EvoZoneMode.FOLLOW_SCHEDULE: PRESET_NONE,
    EvoZoneMode.TEMPORARY_OVERRIDE: "temporary",
    EvoZoneMode.PERMANENT_OVERRIDE: "permanent",
}
HA_PRESET_TO_EVO = {v: k for k, v in EVO_PRESET_TO_HA.items()}

SET_SYSTEM_MODE_SCHEMA = {
    vol.Required(ATTR_MODE): cv.string,
    vol.Exclusive(ATTR_DURATION, "temporary"): vol.All(
        cv.time_period, vol.Range(min=timedelta(hours=0), max=timedelta(hours=24))
    ),
    vol.Exclusive(ATTR_PERIOD, "temporary"): vol.All(
        cv.time_period, vol.Range(min=timedelta(days=1), max=timedelta(days=99))
    ),
}
SET_ZONE_OVERRIDE_SCHEMA = {
    vol.Required(ATTR_SETPOINT): vol.All(
        vol.Coerce(float), vol.Range(min=4.0, max=35.0)
    ),
    vol.Optional(ATTR_DURATION): vol.All(
        cv.time_period, vol.Range(min=timedelta(days=0), max=timedelta(days=1))
    ),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EvoConfigEntry,
    async_add_entities: entity_platform.AddEntitiesCallback,
) -> None:
    """Set up the climate platform and its entity services."""
    coordinator = entry.runtime_data.coordinator
    tcs = entry.runtime_data.tcs

    entities: list[EvoController | EvoZone] = [EvoController(coordinator, tcs)]
    for zone in tcs.zones:
        if is_valid_zone(zone):
            entities.append(EvoZone(coordinator, zone))
        else:
            _LOGGER.warning("Ignoring unsupported zone: %s (%s)", zone.name, zone.id)

    async_add_entities(entities)
    for entity in entities:
        await entity.update_attrs()

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        EvoService.SET_SYSTEM_MODE, SET_SYSTEM_MODE_SCHEMA, "async_set_system_mode"
    )
    platform.async_register_entity_service(
        EvoService.SET_ZONE_OVERRIDE,
        SET_ZONE_OVERRIDE_SCHEMA,
        "async_set_zone_override",
    )
    platform.async_register_entity_service(
        EvoService.CLEAR_ZONE_OVERRIDE, None, "async_clear_zone_override"
    )


class EvoClimateEntity(EvoEntity, ClimateEntity):
    """Base for evohome climate entities; unsupported services raise cleanly."""

    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    async def async_set_system_mode(self, **kwargs: Any) -> None:
        """Only the controller supports this."""
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="controller_only_service",
            translation_placeholders={"service": EvoService.SET_SYSTEM_MODE},
        )

    async def async_set_zone_override(self, **kwargs: Any) -> None:
        """Only zones support this."""
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="zone_only_service",
            translation_placeholders={"service": EvoService.SET_ZONE_OVERRIDE},
        )

    async def async_clear_zone_override(self) -> None:
        """Only zones support this."""
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="zone_only_service",
            translation_placeholders={"service": EvoService.CLEAR_ZONE_OVERRIDE},
        )


class EvoZone(EvoChild, EvoClimateEntity):
    """An evohome heating zone."""

    _attr_preset_modes = list(HA_PRESET_TO_EVO)

    _evo_device: evo.Zone
    _evo_id_attr = "zone_id"
    _evo_state_attr_names = (SZ_SETPOINT_STATUS, SZ_TEMPERATURE_STATUS)

    def __init__(
        self, coordinator: EvoDataUpdateCoordinator, evo_device: evo.Zone
    ) -> None:
        """Initialise a heating zone."""
        super().__init__(coordinator, evo_device)

        self._attr_unique_id = unique_zone_id(evo_device)
        self._attr_precision = (
            PRECISION_TENTHS
            if coordinator.client_v1
            else evo_device.setpoint_capabilities["value_resolution"]
        )
        self._attr_supported_features = (
            ClimateEntityFeature.PRESET_MODE
            | ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TURN_OFF
            | ClimateEntityFeature.TURN_ON
        )

    @override
    async def async_clear_zone_override(self) -> None:
        """Return the zone to following its schedule."""
        await self.coordinator.call_client_api(self._evo_device.reset())

    @override
    async def async_set_zone_override(
        self, setpoint: float, duration: timedelta | None = None
    ) -> None:
        """Override the zone setpoint, permanently or for a duration."""
        temperature = max(min(setpoint, self.max_temp), self.min_temp)

        if duration is None:
            until = None
        elif duration.total_seconds() == 0:
            await self._update_schedule()
            until = self.setpoints.get("next_sp_from")
        else:
            until = dt_util.now() + duration

        until = dt_util.as_utc(until) if until else None
        await self.coordinator.call_client_api(
            self._evo_device.set_temperature(temperature, until=until)
        )

    @property
    @override
    def name(self) -> str:
        """Return the zone name (zones can be renamed)."""
        return self._evo_device.name

    @property
    @override
    def hvac_mode(self) -> HVACMode | None:
        """Return the current operating mode of the zone."""
        if self._evo_tcs.mode in (EvoSystemMode.AWAY, EvoSystemMode.HEATING_OFF):
            return HVACMode.AUTO
        if self.target_temperature is None:
            return None
        if self.target_temperature <= self.min_temp:
            return HVACMode.OFF
        return HVACMode.HEAT

    @property
    @override
    def target_temperature(self) -> float | None:
        """Return the zone target temperature."""
        return self._evo_device.target_heat_temperature

    @property
    @override
    def preset_mode(self) -> str | None:
        """Return the current preset mode."""
        if self._evo_tcs.mode in (EvoSystemMode.AWAY, EvoSystemMode.HEATING_OFF):
            return TCS_PRESET_TO_HA.get(self._evo_tcs.mode)
        return EVO_PRESET_TO_HA.get(self._evo_device.mode)

    @property
    @override
    def min_temp(self) -> float:
        """Return the minimum target temperature."""
        return self._evo_device.min_heat_setpoint

    @property
    @override
    def max_temp(self) -> float:
        """Return the maximum target temperature."""
        return self._evo_device.max_heat_setpoint

    @override
    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set a new target temperature."""
        temperature = kwargs[ATTR_TEMPERATURE]

        if (until := kwargs.get("until")) is None:
            if self._evo_device.mode == EvoZoneMode.TEMPORARY_OVERRIDE:
                until = self._evo_device.until
            if self._evo_device.mode == EvoZoneMode.FOLLOW_SCHEDULE:
                await self._update_schedule()
                until = self.setpoints.get("next_sp_from")

        until = dt_util.as_utc(until) if until else None
        await self.coordinator.call_client_api(
            self._evo_device.set_temperature(temperature, until=until)
        )

    @override
    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set the zone to one of its native operating modes."""
        if hvac_mode == HVACMode.OFF:
            await self.coordinator.call_client_api(
                self._evo_device.set_temperature(self.min_temp, until=None)
            )
        else:  # HVACMode.HEAT
            await self.coordinator.call_client_api(self._evo_device.reset())

    @override
    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the preset mode, or revert to following the schedule."""
        evo_preset_mode = HA_PRESET_TO_EVO.get(preset_mode, EvoZoneMode.FOLLOW_SCHEDULE)

        if evo_preset_mode == EvoZoneMode.FOLLOW_SCHEDULE:
            await self.coordinator.call_client_api(self._evo_device.reset())
            return

        if evo_preset_mode == EvoZoneMode.TEMPORARY_OVERRIDE:
            await self._update_schedule()
            until = self.setpoints.get("next_sp_from")
        else:
            until = None

        temperature = self._evo_device.target_heat_temperature
        until = dt_util.as_utc(until) if until else None
        await self.coordinator.call_client_api(
            self._evo_device.set_temperature(temperature, until=until)
        )


class EvoController(EvoClimateEntity):
    """The controller (TCS); modelled as climate to expose system modes."""

    _attr_icon = "mdi:thermostat-box"
    _attr_precision = PRECISION_TENTHS

    _evo_device: evo.ControlSystem
    _evo_id_attr = "system_id"
    _evo_state_attr_names = (SZ_SYSTEM_MODE_STATUS,)

    def __init__(
        self, coordinator: EvoDataUpdateCoordinator, evo_device: evo.ControlSystem
    ) -> None:
        """Initialise the controller."""
        super().__init__(coordinator, evo_device)

        self._attr_unique_id = evo_device.id
        self._attr_name = evo_device.location.name

        self._evo_modes = [m[SZ_SYSTEM_MODE] for m in evo_device.allowed_system_modes]
        self._attr_preset_modes = [
            TCS_PRESET_TO_HA[m] for m in self._evo_modes if m in TCS_PRESET_TO_HA
        ]
        self._attr_supported_features = (
            ClimateEntityFeature.TURN_OFF | ClimateEntityFeature.TURN_ON
        )
        if self._attr_preset_modes:
            self._attr_supported_features |= ClimateEntityFeature.PRESET_MODE

    @override
    async def async_set_system_mode(
        self,
        mode: str,
        duration: timedelta | None = None,
        period: timedelta | None = None,
    ) -> None:
        """Set the controller's system mode (optionally temporary)."""
        if period is not None:
            until = dt_util.start_of_local_day() + period
        elif duration is not None:
            until = dt_util.now() + duration
        else:
            until = None
        await self._set_tcs_mode(mode, until=until)

    async def _set_tcs_mode(self, mode: str, until: datetime | None = None) -> None:
        until = dt_util.as_utc(until) if until else None
        try:
            await self.coordinator.call_client_api(
                self._evo_device.set_mode(mode, until=until)
            )
        except evo.InvalidSystemModeError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_system_mode",
                translation_placeholders={"error": str(err)},
            ) from err

    @property
    @override
    def hvac_mode(self) -> HVACMode:
        """Return the controller's operating mode."""
        return (
            HVACMode.OFF
            if self._evo_device.mode in (EvoSystemMode.HEATING_OFF, EvoSystemMode.OFF)
            else HVACMode.HEAT
        )

    @property
    @override
    def current_temperature(self) -> float | None:
        """Return the average current temperature of the heating zones."""
        temps = [
            z.temperature for z in self._evo_device.zones if z.temperature is not None
        ]
        return round(sum(temps) / len(temps), 1) if temps else None

    @property
    @override
    def preset_mode(self) -> str | None:
        """Return the current preset mode."""
        return TCS_PRESET_TO_HA.get(self._evo_device.mode)

    @override
    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Controllers have no target temperature."""
        raise NotImplementedError("Controllers don't have a target temperature")

    @override
    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set the controller's operating mode."""
        if hvac_mode == HVACMode.HEAT:
            mode = (
                EvoSystemMode.AUTO
                if EvoSystemMode.AUTO in self._evo_modes
                else EvoSystemMode.HEAT
            )
        elif hvac_mode == HVACMode.OFF:
            mode = (
                EvoSystemMode.HEATING_OFF
                if EvoSystemMode.HEATING_OFF in self._evo_modes
                else EvoSystemMode.OFF
            )
        else:
            raise HomeAssistantError(f"Invalid hvac_mode: {hvac_mode}")
        await self._set_tcs_mode(mode)

    @override
    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the preset mode, or revert to 'Auto'."""
        await self._set_tcs_mode(HA_PRESET_TO_TCS.get(preset_mode, EvoSystemMode.AUTO))
