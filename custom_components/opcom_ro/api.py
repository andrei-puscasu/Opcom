"""OPCOM day-ahead market CSV client.

Fetches the public "Raport PIP si volum tranzactionat" CSV export from
opcom.ro and parses it into structured :class:`DayResult` objects.

The export endpoint returns 96 native 15-minute intervals regardless of the
``resolution`` query parameter, so we always request PT15M and aggregate
locally (see :mod:`helpers`). An empty response body means OPCOM has not
published results for that delivery day yet (typically tomorrow before
~13:00-15:00 market time). An HTTP 403 means OPCOM's WAF is refusing the
request (rate-limit escalation / fingerprint block / next-day file around
publication); we back off and retry on the next poll rather than hammering.
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import date, datetime, timedelta
from typing import Iterable

from .const import MARKET_TZ, OPCOM_URL_TEMPLATE
from .models import DayResult, Interval

_LOGGER = logging.getLogger(__name__)

# OPCOM sits behind a WAF that rejects bare Python clients (HTTP 403) and
# has been observed to 403 aiohttp even with a browser User-Agent, while the
# same URL from a browser/curl succeeds. We send a full browser-like header
# set (not just the UA) to avoid being fingerprinted as a bot.
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Headers a real browser sends when navigating to the CSV export from the
# OPCOM grafice page. Sent on both the sync and async paths.
_BROWSER_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "ro-RO,ro;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": (
        "https://www.opcom.ro/grafice-ip-raportPIP-si-volumTranzactionat/ro"
    ),
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

# Column-0 markers that announce the per-interval header row (ro / en).
_INTERVAL_HEADER_MARKERS = ("Zona de tranzactionare", "Trading Zone")

# Column-0 prefixes for the summary (Base / Peak / Off-Peak) rows.
_SUMMARY_PREFIXES = {
    "base": "ROPEX_DAM_Base",
    "peak": "ROPEX_DAM_Peak",
    "off_peak": "ROPEX_DAM_Off_Peak",
}

_NATIVE_INTERVALS = 96
_NATIVE_STEP = timedelta(minutes=15)


def build_url(delivery_day: date, lang: str) -> str:
    """Build the OPCOM export URL for a delivery day and language."""
    return OPCOM_URL_TEMPLATE.format(date=delivery_day.strftime("%d/%m/%Y"), lang=lang)


def _safe_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_csv(text: str, delivery_day: date) -> DayResult | None:
    """Parse an OPCOM CSV export into a :class:`DayResult`.

    Returns ``None`` when the response contains no per-interval data (i.e. the
    results for that day have not been published yet).
    """
    if not text or not text.strip():
        return None

    result = DayResult(delivery_day=delivery_day)
    midnight = datetime.combine(delivery_day, datetime.min.time(), tzinfo=MARKET_TZ)

    reader = csv.reader(io.StringIO(text))
    in_intervals = False
    for row in reader:
        if not row:
            continue
        first = (row[0] or "").strip()

        # Detect the per-interval header row.
        if first in _INTERVAL_HEADER_MARKERS:
            in_intervals = True
            continue

        # Summary rows can appear before the interval header.
        for key, prefix in _SUMMARY_PREFIXES.items():
            if first.startswith(prefix):
                val = _safe_float(row[1]) if len(row) > 1 else None
                if val is not None:
                    if key == "base":
                        result.base_price = val
                    elif key == "peak":
                        result.peak_price = val
                    elif key == "off_peak":
                        result.off_peak_price = val
                break

        if not in_intervals:
            continue
        if first.lower() != "romania":
            continue
        if len(row) < 3:
            continue

        idx = _safe_float(row[1])
        price = _safe_float(row[2])
        if idx is None or price is None:
            continue
        idx_int = int(idx)
        if idx_int < 1 or idx_int > _NATIVE_INTERVALS:
            continue

        volume = _safe_float(row[3]) if len(row) > 3 else 0.0
        buy = _safe_float(row[4]) if len(row) > 4 else 0.0
        sell = _safe_float(row[5]) if len(row) > 5 else 0.0

        result.intervals.append(
            Interval(
                index=idx_int,
                start=midnight + (idx_int - 1) * _NATIVE_STEP,
                price=price,
                volume=volume or 0.0,
                buy_volume=buy or 0.0,
                sell_volume=sell or 0.0,
            )
        )

    # Keep intervals sorted by index (they normally already are).
    result.intervals.sort(key=lambda i: i.index)
    if not result.intervals:
        _LOGGER.debug("OPCOM CSV for %s contained no Romania intervals", delivery_day)
        return None
    return result


async def async_fetch_day(
    hass,
    delivery_day: date,
    lang: str,
) -> DayResult | None:
    """Fetch and parse one delivery day from OPCOM.

    Raises :class:`Exception` on transport errors so the coordinator can apply
    retry/backoff. Returns ``None`` when the day is not available — either an
    empty body (not published yet) or an HTTP 403 (WAF/rate-limit; back off).
    """
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    session = async_get_clientsession(hass)
    url = build_url(delivery_day, lang)
    _LOGGER.debug("Fetching OPCOM CSV: %s", url)
    async with session.get(url, headers=_BROWSER_HEADERS, timeout=30) as resp:
        if resp.status == 403:
            # OPCOM's WAF refused us — observed both for the next-day file
            # around publication time and as a rate-limit escalation against
            # the HA server's IP after a burst of requests. Either way the
            # right move is to back off and let the next poll retry, NOT to
            # hammer it with retries (which makes an IP block worse).
            # Returning None marks the day unavailable until the next poll.
            _LOGGER.warning(
                "OPCOM returned 403 for %s (WAF/rate-limit); backing off until next poll",
                delivery_day,
            )
            return None
        resp.raise_for_status()
        text = await resp.text()
    return parse_csv(text, delivery_day)


# --- Standalone helpers (used by tests / CLI) -----------------------------

def fetch_day_sync(delivery_day: date, lang: str = "ro") -> DayResult | None:
    """Synchronous fetch using urllib (for local testing outside HA)."""
    import urllib.request

    # urllib does not auto-decompress, so do not advertise gzip/br here
    # (aiohttp, used in production, does and is unaffected).
    headers = {k: v for k, v in _BROWSER_HEADERS.items() if k != "Accept-Encoding"}
    url = build_url(delivery_day, lang)
    req = urllib.request.Request(url, headers=headers)  # noqa: S310
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
        raw = resp.read()
    encoding = resp.headers.get_content_charset() or "utf-8"
    return parse_csv(raw.decode(encoding, errors="replace"), delivery_day)


__all__: Iterable[str] = (
    "build_url",
    "parse_csv",
    "async_fetch_day",
    "fetch_day_sync",
)