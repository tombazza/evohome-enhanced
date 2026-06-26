"""Tests for the description-driven sensor/binary_sensor value logic.

These import Home Assistant for the entity-description base classes, so they run
in CI (where HA is installed) and skip gracefully where it is not.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("homeassistant")

from custom_components.evohome_enhanced import binary_sensor, sensor


def _coordinator(temps: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(temps=temps or {})


def _zone(**kwargs) -> SimpleNamespace:
    defaults = {
        "id": "z1",
        "temperature": 20.0,
        "target_heat_temperature": 21.0,
        "mode": "FollowSchedule",
        "active_faults": [],
        "status": {"heatDemand": 0},
    }
    return SimpleNamespace(**(defaults | kwargs))


def _desc(descriptions, key):
    return next(d for d in descriptions if d.key == key)


class TestSensorValues:
    def test_temperature_prefers_high_precision(self) -> None:
        desc = _desc(sensor.ZONE_SENSORS, "temperature")
        zone = _zone()
        coord = _coordinator({"z1": 20.4})
        assert desc.value_fn(zone, coord) == 20.4

    def test_temperature_falls_back(self) -> None:
        desc = _desc(sensor.ZONE_SENSORS, "temperature")
        assert desc.value_fn(_zone(), _coordinator()) == 20.0

    def test_setpoint(self) -> None:
        desc = _desc(sensor.ZONE_SENSORS, "setpoint")
        assert desc.value_fn(_zone(), _coordinator()) == 21.0

    def test_heat_demand_exists_only_when_reported(self) -> None:
        desc = _desc(sensor.ZONE_SENSORS, "heat_demand")
        assert desc.exists_fn(_zone(status={"heatDemand": 55})) is True
        assert desc.exists_fn(_zone(status={})) is False

    def test_heat_demand_value(self) -> None:
        desc = _desc(sensor.ZONE_SENSORS, "heat_demand")
        assert desc.value_fn(_zone(status={"heatDemand": 55}), _coordinator()) == 55.0

    def test_mode(self) -> None:
        desc = _desc(sensor.ZONE_SENSORS, "mode")
        assert desc.value_fn(_zone(mode="PermanentOverride"), _coordinator()) == (
            "PermanentOverride"
        )


class TestBinarySensorValues:
    def test_zone_fault_off(self) -> None:
        desc = _desc(binary_sensor.ZONE_BINARY_SENSORS, "fault")
        assert desc.value_fn(_zone(active_faults=[]), _coordinator()) is False

    def test_zone_fault_on(self) -> None:
        desc = _desc(binary_sensor.ZONE_BINARY_SENSORS, "fault")
        zone = _zone(active_faults=[{"faultType": "low_battery"}])
        assert desc.value_fn(zone, _coordinator()) is True

    def test_calling_for_heat(self) -> None:
        desc = _desc(binary_sensor.ZONE_BINARY_SENSORS, "calling_for_heat")
        assert desc.value_fn(_zone(status={"heatDemand": 30}), _coordinator()) is True
        assert desc.value_fn(_zone(status={"heatDemand": 0}), _coordinator()) is False
