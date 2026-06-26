"""Unit tests for the framework-free logic layer.

These run on plain pytest (no Home Assistant required) and cover every branch of
the integration's decision logic.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

# Load logic.py standalone: it has no HA/library imports, so it must be testable
# without importing the (HA-dependent) package __init__.
_LOGIC_PATH = (
    Path(__file__).parent.parent
    / "custom_components"
    / "evohome_enhanced"
    / "logic.py"
)
_spec = importlib.util.spec_from_file_location("evo_logic", _LOGIC_PATH)
assert _spec and _spec.loader
logic = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(logic)

calling_for_heat = logic.calling_for_heat
has_active_fault = logic.has_active_fault
heat_demand_pct = logic.heat_demand_pct
precise_temperature = logic.precise_temperature
zone_unique_id = logic.zone_unique_id


class TestZoneUniqueId:
    def test_distinct_ids_pass_through(self) -> None:
        assert zone_unique_id("zone-1", "tcs-9") == "zone-1"

    def test_colliding_id_is_suffixed(self) -> None:
        assert zone_unique_id("same", "same") == "samez"


class TestPreciseTemperature:
    def test_prefers_high_resolution(self) -> None:
        assert precise_temperature(20.4, 20.0) == 20.4

    def test_falls_back_when_high_res_missing(self) -> None:
        assert precise_temperature(None, 20.0) == 20.0

    def test_zero_high_res_is_not_treated_as_missing(self) -> None:
        # 0.0 is falsy but valid; must not fall back to the v2 value.
        assert precise_temperature(0.0, 20.0) == 0.0

    def test_both_missing(self) -> None:
        assert precise_temperature(None, None) is None


class TestHeatDemand:
    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (None, None),
            ({}, None),
            ({"heatDemand": None}, None),
            ({"heatDemand": 0}, 0.0),
            ({"heatDemand": 100}, 100.0),
            ({"heatDemand": 42.64}, 42.6),
        ],
    )
    def test_heat_demand_pct(self, status: dict | None, expected: float | None) -> None:
        assert heat_demand_pct(status) == expected


class TestCallingForHeat:
    def test_unknown_when_no_demand_field(self) -> None:
        assert calling_for_heat({}) is None
        assert calling_for_heat(None) is None

    def test_false_at_zero_demand(self) -> None:
        assert calling_for_heat({"heatDemand": 0}) is False

    def test_true_with_demand(self) -> None:
        assert calling_for_heat({"heatDemand": 30}) is True


class TestHasActiveFault:
    def test_no_faults(self) -> None:
        assert has_active_fault([]) is False
        assert has_active_fault(None) is False
        assert has_active_fault([], None, ()) is False

    def test_any_fault_set_trips(self) -> None:
        assert has_active_fault([], [{"fault": "x"}]) is True

    def test_single_fault(self) -> None:
        assert has_active_fault([{"fault": "low_battery"}]) is True
