"""Diagnostics support for evohome_enhanced."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

if TYPE_CHECKING:
    from . import EvoConfigEntry

TO_REDACT = {"username", "password", "access_token", "refresh_token", "session_id"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: EvoConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data.coordinator
    return {
        "options": dict(entry.options),
        "high_precision": coordinator.client_v1 is not None,
        "high_precision_temps": coordinator.temps,
        "location_status": async_redact_data(coordinator.data, TO_REDACT),
    }
