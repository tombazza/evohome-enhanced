# Evohome Enhanced

A modern, HACS-installable Home Assistant integration for **EMEA/EU Honeywell
Total Connect Comfort** systems (Evohome, Round Thermostat, etc.).

It is built on the same async [`evohome-async`](https://github.com/zxdavb/evohome-async)
client as the core integration, but fixes its biggest limitation: **rich data is
buried inside climate `extra_state_attributes`** where it can't drive sensor
cards, history graphs or long-term statistics, and can't be used cleanly in
automations.

## Why this exists

The official `evohome` integration exposes only `climate`, `water_heater` and a
reset `button`, and is still YAML-configured (`quality_scale: legacy`). Useful
data — per-zone measured temperature, setpoint, heat demand, fault state — is
stuffed into a single `status` attribute blob.

Evohome Enhanced keeps the proven climate/water-heater logic and adds:

- **First-class `sensor` entities** — per-zone temperature (with optional
  0.1 °C high-precision values), setpoint, heat demand (where reported), zone
  mode, and system mode. These get proper device classes, so they work with
  sensor cards and the statistics/history engine out of the box.
- **First-class `binary_sensor` entities** — per-zone/DHW/system fault
  (`device_class: problem`), "calling for heat" (`device_class: heat`), and DHW
  heating activity (`device_class: running`).
- **A UI config flow** — no YAML. Plus an options flow for scan interval and the
  high-precision toggle.
- **A device registry** — every zone, the DHW and the controller appear as
  devices, with sensors and climate grouped under them.
- **Diagnostics** download support.

A single `DataUpdateCoordinator` drives every platform, so the extra entities
are read-only projections of already-fetched data and cost **no additional API
calls**.

## Installation (HACS)

1. Add this repository as a custom repository in HACS (category: *Integration*).
2. Install **Evohome Enhanced** and restart Home Assistant.
3. Go to *Settings → Devices & Services → Add Integration → Evohome Enhanced*
   and sign in with your Total Connect Comfort account.

> It can run alongside the built-in `evohome` integration (different domain),
> which is handy for comparison — but disable one to avoid double polling and
> hitting the vendor's rate limit.

## Entities

| Platform | Per zone | Per DHW | Per controller |
|---|---|---|---|
| `climate` | zone thermostat | — | system modes |
| `water_heater` | — | hot water | — |
| `sensor` | temperature, setpoint, heat demand\*, mode | temperature, heat demand\* | system mode |
| `binary_sensor` | fault, calling for heat\* | fault, heating | fault |
| `button` | reset | reset | reset |

\* Only created when the vendor's API reports heat demand for that device.

## Services

`refresh_system`, `set_system_mode`, `set_zone_override`, `clear_zone_override`,
`set_dhw_override`. See `services.yaml` for parameters.

## Development

The decision logic lives in a pure, framework-free module
(`custom_components/evohome_enhanced/logic.py`) so it can be unit-tested without
Home Assistant:

```bash
pip install -r requirements-test.txt   # Python 3.13 for the HA-coupled tests
ruff check custom_components tests
pytest tests/ -q
```

`tests/test_logic.py` runs on any Python ≥3.11 (no HA needed);
`tests/test_entities.py` exercises the sensor/binary-sensor value functions and
skips automatically where Home Assistant isn't installed.

## Disclaimer

Not affiliated with or endorsed by Honeywell or Resideo. Use at your own risk.
