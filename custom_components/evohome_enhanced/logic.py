"""Pure, framework-free logic for the evohome_enhanced integration.

This module deliberately imports neither Home Assistant nor evohome-async so it
can be unit-tested in isolation. Everything here is a small, total function.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

MANUFACTURER = "Honeywell"


def zone_unique_id(zone_id: str, tcs_id: str) -> str:
    """Return a collision-free id for a zone.

    Some systems give a zone the same id as its parent controller; append ``z``
    so the zone entity never clashes with the controller entity.
    """
    return f"{zone_id}z" if zone_id == tcs_id else zone_id


def precise_temperature(
    high_res: float | None, fallback: float | None
) -> float | None:
    """Prefer a high-precision (v1 API) temperature, else the v2 value."""
    return fallback if high_res is None else high_res


def heat_demand_pct(status: Mapping[str, Any] | None) -> float | None:
    """Return a zone/DHW heat demand as a percentage, when the API reports it.

    The TCC API expresses ``heatDemand`` as a 0-100 percentage; not every system
    exposes it, in which case ``None`` is returned and no entity is created.
    """
    if not status:
        return None
    value = status.get("heatDemand")
    return None if value is None else round(float(value), 1)


def calling_for_heat(status: Mapping[str, Any] | None) -> bool | None:
    """Return whether a zone/DHW is currently demanding heat (demand > 0)."""
    demand = heat_demand_pct(status)
    return None if demand is None else demand > 0


def has_active_fault(*fault_sets: Sequence[Any] | None) -> bool:
    """Return True if any of the supplied fault collections is non-empty."""
    return any(bool(faults) for faults in fault_sets if faults is not None)
