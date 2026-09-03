# OPCOM Romania Prices (Home Assistant)

A free, open-source Home Assistant custom integration that imports **OPCOM
day-ahead electricity prices** (Piața pentru Ziua Următoare / PZU / DAM) from
[opcom.ro](https://www.opcom.ro/grafice-ip-raportPIP-si-volumTranzactionat/ro)
and turns them into sensors and ready-to-use binary signals for **battery
charge/discharge, EV charging and heat-pump automations**.

No license server, no trial, no phone-home. Just the public OPCOM CSV export,
parsed locally.

> This integration is an independent re-implementation. It is **not** a fork of
> any existing OPCOM integration and shares no code with them. It was built
> from scratch after the OPCOM export endpoint changed (it now always returns
> 96 native 15-minute intervals), which broke older integrations that expected
> 24 hourly rows.

## Why this one

- **Robust to OPCOM changes.** Always fetches the native 15-minute granularity
  (96 intervals/day) and aggregates to 30/60 minutes locally. The server's
  `resolution` query parameter is currently ignored — relying on it is what
  breaks other integrations.
- **No license / no accounts.** Fully MIT-licensed. Reads a public CSV.
- **Battery-aware.** Optimal cheap/expensive windows via a sliding-window +
  greedy non-overlap algorithm, plus optional price thresholds and percentile
  gates for automations.
- **RON or EUR.** Pick `RON` (lei/MWh, Romanian source) or `EUR` (EUR/MWh,
  English source) per instance.
- **Chart-ready.** Each day's full price curve is exposed as the `prices`
  attribute (`HH:MM` → price) so you can plot it with a chart card.

## Installation

### HACS (recommended)

1. In HACS → **Custom repositories**, add this repo as type **Integration**.
2. Search for **OPCOM Romania Prices** and install it.
3. Restart Home Assistant.
4. **Settings → Devices & Services → Add integration** → search "OPCOM Romania".

### Manual

Copy the `custom_components/opcom_ro/` folder into your
`custom_components/` directory, restart Home Assistant, then add the
integration as above.

## Configuration

All options are in the integration dialog (**Configure** on the entry):

| Option | Default | Description |
|---|---|---|
| Currency | RON | `RON` (lei/MWh) or `EUR` (EUR/MWh) |
| Resolutions | 15 min | Multi-select: 15 / 30 / 60 min |
| Refresh interval | 5 min | How often to re-fetch OPCOM |
| Window duration | 60 min | Length of each optimal window (multiple of 15) |
| Number of windows | 3 | How many cheap/expensive windows to select |
| Low price threshold | — | Optional: only import below this price |
| High price threshold | — | Optional: only export above this price |
| Cheap percentile | 25% | Bottom-rank gate for `cheap_percentile_now` |
| Expensive percentile | 75% | Top-rank gate for `expensive_percentile_now` |

Each enabled resolution creates its own device (`OPCOM Romania 15 min`, etc.).

## Entities (per resolution)

**Sensors**

| Entity | State | Useful attributes |
|---|---|---|
| Price now | current interval price | `interval_start/end`, `volume_mwh`, `prices` (full today curve) |
| Next price | next interval price | `interval_start/end` |
| Average today | daily average price | `base_price`, `peak_price`, `off_peak_price` |
| Average tomorrow | tomorrow's average | `prices` (full tomorrow curve) |
| Cheapest window today | best window avg price | `windows[]` (start/end/avg), `remaining_intervals` |
| Most expensive window today | best window avg price | `windows[]` |
| Cheapest window tomorrow | best window avg price | `windows[]` |
| Most expensive window tomorrow | best window avg price | `windows[]` |
| Current price percentile | 0–100 | `current_price`, `percentile_low/high` |

**Binary sensors**

| Entity | ON when |
|---|---|
| Should charge now | inside a cheapest window AND (no low threshold or price ≤ threshold) |
| Should discharge now | inside a most-expensive window AND (no high threshold or price ≥ threshold) |
| Price below threshold | current price < low threshold (created only if set) |
| Price above threshold | current price > high threshold (created only if set) |
| Cheap price (percentile) | current price rank ≤ cheap percentile |
| Expensive price (percentile) | current price rank ≥ expensive percentile |

> ⚠️ Covering more hours than exist in a day can make charge and discharge
> overlap. Keep `window_duration × number_of_windows` well under 24 h.

## Automation examples

### Charge a battery when electricity is cheap

```yaml
alias: "Battery: charge on cheap window"
trigger:
  platform: state
  entity_id: binary_sensor.opcom_romania_15_min_should_charge_now
  to: "on"
action:
  - service: switch.turn_on
    target:
      entity_id: switch.battery_charge
```

### Discharge / export when expensive

```yaml
alias: "Battery: discharge on expensive window"
trigger:
  platform: state
  entity_id: binary_sensor.opcom_romania_15_min_should_discharge_now
  to: "on"
action:
  - service: switch.turn_on
    target:
      entity_id: switch.battery_discharge
```

### Plot today's price curve (ApexCharts card)

```yaml
type: custom:apexcharts-card
header:
  show: true
  title: OPCOM preturi astazi
series:
  - entity: sensor.opcom_romania_15_min_current_price
    attribute: prices
    type: column
```

## Notes

- OPCOM publishes **next-day** results between roughly **13:00 and 15:00
  Romania time**. Until then, tomorrow sensors show *unavailable*. This is
  expected, not a bug.
- All interval math uses the **Europe/Bucharest** timezone so "current
  interval" matches the Romanian delivery day regardless of your HA server's
  timezone.
- Prices from the `RON` source are in **lei/MWh**; the `EUR` source is in
  **EUR/MWh**. Both come straight from OPCOM's public export.

## Troubleshooting & sharing logs

Two ways to capture diagnostic info to send to a maintainer:

1. **Diagnostics (quick).** *Devices & Services → OPCOM Romania → ⋮ → Download
   diagnostics.* Produces a redacted JSON snapshot (config, last update status,
   today/tomorrow price summary). No personal data.
2. **Debug log file (deeper).** In *Configure*, enable **Enable debug log file**
   → the integration writes fetch events to `<config>/opcom_ro_debug.log`
   (512 KB, one rollover). Use the **Clear debug log** button to start a clean
   capture, **Refresh now** to force a fetch, then share the file. Turn the
   option off again when done.

The integration also logs normally under the `custom_components.opcom_ro`
logger; enable debug in HA's logger to see it in the main log.

## Development & testing

```bash
# syntax + offline parser test (no Home Assistant needed)
python -m py_compile custom_components/opcom_ro/*.py
python -m unittest discover -s tests

# quick live check against opcom.ro
python -c "from custom_components.opcom_ro.api import fetch_day_sync; \
  from datetime import date; \
  print(fetch_day_sync(date(2026,9,2)).intervals[0].price)"
```

## License

MIT — see [LICENSE](LICENSE). Data is © OPCOM; this integration only reads
their public export endpoint.