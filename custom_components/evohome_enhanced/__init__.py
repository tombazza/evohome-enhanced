"""The evohome_enhanced integration (EMEA/EU Honeywell TCC systems)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

import evohomeasync as ec1
import evohomeasync2 as ec2
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    Platform,
)
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_HIGH_PRECISION,
    CONF_LOCATION_IDX,
    DOMAIN,
    SCAN_INTERVAL_DEFAULT,
    STORAGE_KEY,
    EvoService,
)
from .coordinator import EvoDataUpdateCoordinator
from .storage import TokenManager

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.SENSOR,
    Platform.WATER_HEATER,
]


@dataclass
class EvoData:
    """Runtime data stored on the config entry."""

    coordinator: EvoDataUpdateCoordinator
    loc_idx: int
    tcs: ec2.ControlSystem


type EvoConfigEntry = ConfigEntry[EvoData]


async def async_setup_entry(hass: HomeAssistant, entry: EvoConfigEntry) -> bool:
    """Set up evohome_enhanced from a config entry."""
    token_manager = TokenManager(
        hass,
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        async_get_clientsession(hass),
        storage_key=f"{STORAGE_KEY}_{entry.entry_id}",
    )
    high_precision = entry.options.get(CONF_HIGH_PRECISION, True)

    coordinator = EvoDataUpdateCoordinator(
        hass,
        _LOGGER,
        ec2.EvohomeClient(token_manager),
        name=entry.title,
        location_idx=entry.data[CONF_LOCATION_IDX],
        update_interval=timedelta(
            seconds=entry.options.get(CONF_SCAN_INTERVAL, SCAN_INTERVAL_DEFAULT)
        ),
        client_v1=ec1.EvohomeClient(token_manager) if high_precision else None,
        config_entry=entry,
    )

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = EvoData(
        coordinator=coordinator, loc_idx=coordinator.loc_idx, tcs=coordinator.tcs
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_register_services(hass)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EvoConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(hass: HomeAssistant, entry: EvoConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


def _async_register_services(hass: HomeAssistant) -> None:
    """Register the (domain-wide) refresh service exactly once."""
    if hass.services.has_service(DOMAIN, EvoService.REFRESH_SYSTEM):
        return

    async def _refresh(_call: ServiceCall) -> None:
        for entry in hass.config_entries.async_loaded_entries(DOMAIN):
            await entry.runtime_data.coordinator.async_refresh()

    hass.services.async_register(DOMAIN, EvoService.REFRESH_SYSTEM, _refresh)
