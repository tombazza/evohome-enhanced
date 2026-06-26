"""Constants for the evohome_enhanced integration."""

from __future__ import annotations

from enum import StrEnum
from typing import Final

DOMAIN: Final = "evohome_enhanced"

MANUFACTURER: Final = "Honeywell"

# Token cache (Store) — suffixed per config entry so accounts never collide.
STORAGE_VER: Final = 1
STORAGE_KEY: Final = DOMAIN

CONF_LOCATION_IDX: Final = "location_idx"
CONF_HIGH_PRECISION: Final = "high_precision"

# Seconds. The vendor rate-limits aggressively, hence a conservative default.
SCAN_INTERVAL_DEFAULT: Final = 300
SCAN_INTERVAL_MINIMUM: Final = 60

ATTR_DURATION: Final = "duration"
ATTR_PERIOD: Final = "period"
ATTR_SETPOINT: Final = "setpoint"


class EvoService(StrEnum):
    """Services exposed by the integration."""

    REFRESH_SYSTEM = "refresh_system"
    SET_SYSTEM_MODE = "set_system_mode"
    SET_ZONE_OVERRIDE = "set_zone_override"
    CLEAR_ZONE_OVERRIDE = "clear_zone_override"
    SET_DHW_OVERRIDE = "set_dhw_override"
