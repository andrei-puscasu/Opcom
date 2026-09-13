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

---

# YellowGrid Romania Prices (Home Assistant)

A second integration in the same repository, `custom_components/yellowgrid/`,
that brings **your actual prosumer import/export prices** from
[yellowgrid.ro](https://www.yellowgrid.ro/) into Home Assistant — per
15-minute interval, for the current day.

## Why a separate integration

OPCOM gives you the **wholesale** day-ahead price (lei/MWh). YellowGrid gives
you the **personalised retail prices you actually pay and earn** (lei/kWh):

* **Import price** — what you pay to consume from the grid. This is a **flat
  retail tariff** (~1.31 lei/kWh) and does *not* move with the wholesale
  market, so the OPCOM "cheap hours" do not change what you pay to import.
* **Export price** — what you earn for injecting surplus PV. This *does* vary
  through the day (roughly `0.5 × PZU + 0.4 lei/kWh`) and is the price that
  matters for export / battery optimisation.

These prices are account-specific and only available behind your authenticated
YellowGrid portal, so this integration reads them from there.

## What you need (one-time)

Two values copied from your YellowGrid portal:

1. **`userToken`** — your session cookie.
2. **`deviceId`** — your plant UUID.

How to copy them (any Chromium browser, e.g. Chrome/Edge):

1. Log in to <https://www.yellowgrid.ro/> normally (phone + SMS).
2. Open the dashboard so a plant is loaded.
3. Open DevTools (**F12**) → **Application** tab → **Storage → Cookies →
   `https://www.yellowgrid.ro`**.
4. Find the cookie named **`userToken`** → copy its **Value** (a long
   URL-encoded string ending in `%3D%3D`). That is your `userToken`.
5. For the `deviceId`: in DevTools go to the **Network** tab, reload the
   dashboard, click any request whose URL contains `earnings?deviceId=` (or
   `summary?deviceId=`). Copy the `deviceId` value from the URL — it is a UUID
   like `766d210c-4a2d-4197-a889-362957da5be2`.

Paste both into the integration's setup form. That's the only manual step.

## How authentication stays alive

YellowGrid's login is gated by a Cloudflare **Turnstile** captcha and **SMS
OTP**, so Home Assistant cannot log in on its own — you paste the cookie once
instead. Once set up, the session **renews itself automatically**: every data
fetch returns a fresh `userToken` via `Set-Cookie` (a sliding session), which
the integration captures and persists. You never need to re-paste under normal
use, and logging into the YellowGrid website on your computer does **not**
invalidate Home Assistant's session (concurrent sessions are allowed).

If the token ever does expire (a 401), the integration raises a re-auth
prompt: paste a fresh `userToken` and it continues. A **Refresh now** button
forces an immediate fetch for testing.

> For a permanently maintenance-free setup, email
> <mailto:office@yellowgrid.ro> and ask for an official API key — that removes
> the cookie/Turnstile dependency entirely.

## Setup

1. Install the repository via HACS (same repo as OPCOM) or copy
   `custom_components/yellowgrid/` into your `custom_components/` folder.
2. Restart Home Assistant.
3. **Settings → Devices & Services → Add integration** → search
   **YellowGrid**.
4. Paste the **`userToken` cookie** and **`deviceId`**, set the refresh
   interval (default 15 min), and submit. The integration runs a live test
   fetch to verify the token before saving.

## Entities

A single **YellowGrid** device is created per plant.

**Sensors**

| Entity | State | Useful attributes |
|---|---|---|
| Import price now | current interval import price (lei/kWh) | `interval_start/end`, `import_prices` + `export_prices` (full 96-point day curve) |
| Export price now | current interval export price (lei/kWh) | same full curve |
| Current interval | 1–96 | `interval_start/end` |
| Imported today | kWh (total) | `delivery_day` |
| Exported today | kWh (total) | `delivery_day` |
| Earnings today | RON (lei, total) | `delivery_day` |
| Savings today | RON (lei, total) | `delivery_day` |

**Button**

| Entity | Action |
|---|---|
| Refresh now | force an immediate earnings fetch |

### Plot the price curve (ApexCharts card)

```yaml
type: custom:apexcharts-card
header:
  show: true
  title: YellowGrid preturi astazi
series:
  - entity: sensor.yellowgrid_current_export_price
    attribute: export_prices
    type: column
    name: Export (lei/kWh)
  - entity: sensor.yellowgrid_current_import_price
    attribute: import_prices
    type: column
    name: Import (lei/kWh)
```

## Notes

* All interval math uses **Europe/Bucharest** so "current interval" matches the
  Romanian delivery day regardless of your HA server's timezone.
* The `userToken` is a real credential. It is stored in Home Assistant's
  encrypted-on-disk config entry storage and is **never** included in
  diagnostics downloads or logs.
* Prices are in **lei/kWh** (energy totals in **kWh**, earnings/savings in
  **RON**), as returned by YellowGrid.
* The integration depends on `curl_cffi` (already required by the OPCOM
  integration) so it presents the same Chrome TLS fingerprint to YellowGrid's
  Cloudflare front-end.