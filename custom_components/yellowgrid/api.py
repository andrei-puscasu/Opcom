"""YellowGrid authenticated earnings client.

Fetches the per-15-minute import/export price curve for a delivery day from
the authenticated ``/api/core-platform/earnings`` endpoint by replaying the
``userToken`` session cookie obtained from the customer portal.

Auth model
----------
YellowGrid's portal is a Next.js SPA behind Cloudflare. Login requires a
Turnstile captcha + SMS OTP, neither of which can be solved headlessly from
Home Assistant. We therefore do **not** log in; the user pastes a ``userToken``
cookie (from their browser's DevTools) once during setup.

The session is a **sliding** one: every authenticated response carries a fresh
``Set-Cookie: userToken=...``. We capture that renewed token and hand it back
to the coordinator, which persists it so the session stays alive indefinitely
without any re-paste. Old and new tokens are both valid concurrently, so a
missed renewal is harmless.

Transport
---------
``curl_cffi`` impersonates Chrome's TLS handshake (same dependency and pattern
as the OPCOM integration) so the Cloudflare front-end does not fingerprint us
as a bot. The import is module-level so the C extension loads once and the
blocking-call detector does not flag it inside the event loop.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

# Module-level (see opcom_ro/api.py for the same rationale): load the curl_cffi
# C extension once at integration load, not on every poll, and keep the
# blocking-call detector quiet.
from curl_cffi import requests as cc_requests

from .const import DAY_MS, IMPERSONATE, MARKET_TZ, YG_REFERER, YG_URL
from .models import YGEarnings, YGInterval

_LOGGER = logging.getLogger(__name__)


class YellowGridAuthError(Exception):
    """The userToken is missing, expired or revoked (HTTP 401)."""


class YellowGridApiError(Exception):
    """A non-auth transport/HTTP error from the YellowGrid API."""


def day_bounds_ms(day: date) -> tuple[int, int]:
    """Epoch-ms [start, end) for a midnight-to-midnight day in Europe/Bucharest."""
    start = datetime.combine(day, datetime.min.time(), tzinfo=MARKET_TZ)
    end = start + timedelta(days=1)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def parse_earnings(payload: dict, delivery_day: date, device_id: str) -> YGEarnings:
    """Parse the JSON earnings response into a :class:`YGEarnings`."""
    raw = payload.get("earningsList") or []
    intervals: list[YGInterval] = []
    for item in sorted(raw, key=lambda x: int(x.get("interval", 0))):
        try:
            idx = int(item["interval"])
        except (KeyError, TypeError, ValueError):
            continue
        if idx < 1 or idx > 96:
            continue
        intervals.append(
            YGInterval(
                index=idx,
                import_price=float(item.get("importPrice", 0.0)),
                export_price=float(item.get("exportPrice", 0.0)),
                import_price_without_tax=float(
                    item.get("importPriceWithoutTax", 0.0)
                ),
                import_price_tax=float(item.get("importPriceTax", 0.0)),
                export=float(item.get("export", 0.0)),
                import_kwh=float(item.get("import", 0.0)),
                savings=float(item.get("savings", 0.0)),
                earnings=float(item.get("earnings", 0.0)),
            )
        )

    return YGEarnings(
        delivery_day=delivery_day,
        device_id=device_id,
        intervals=intervals,
        total_import=float(payload.get("totalImport", 0.0)),
        total_export=float(payload.get("totalExport", 0.0)),
        total_earnings=float(payload.get("totalEarnings", 0.0)),
        total_savings=float(payload.get("totalSavings", 0.0)),
    )


async def async_fetch_earnings(
    user_token: str, device_id: str, delivery_day: date
) -> tuple[YGEarnings, str | None]:
    """Fetch one delivery day's earnings.

    Returns ``(parsed_earnings, renewed_token)`` where ``renewed_token`` is the
    fresh ``userToken`` from the response's ``Set-Cookie`` (or ``None`` if the
    server did not rotate it). Raises :class:`YellowGridAuthError` on HTTP 401
    and :class:`YellowGridApiError` on other failures, so the coordinator can
    map them to the right HA failure type.
    """
    if not user_token or not device_id:
        raise YellowGridAuthError("Missing userToken or deviceId")

    start_ms, end_ms = day_bounds_ms(delivery_day)
    params = {
        "deviceId": device_id,
        "filter": "day",
        "startTime": start_ms,
        "endTime": end_ms,
    }
    cookies = {"userToken": user_token}
    headers = {"Accept": "application/json", "Referer": YG_REFERER}

    try:
        async with cc_requests.AsyncSession(impersonate=IMPERSONATE) as session:
            resp = await session.get(
                YG_URL, params=params, cookies=cookies, headers=headers, timeout=30
            )
    except Exception as err:  # noqa: BLE001 - transport errors
        raise YellowGridApiError(f"Transport error: {err}") from err

    if resp.status_code == 401:
        # Token expired/revoked. The coordinator raises ConfigEntryAuthFailed
        # from this, which triggers HA's built-in reauth flow.
        raise YellowGridAuthError("Authentication failed (HTTP 401)")
    if resp.status_code == 403:
        raise YellowGridApiError(
            f"Forbidden (HTTP 403): {resp.text[:200]}"
        )
    if resp.status_code >= 400:
        raise YellowGridApiError(
            f"HTTP {resp.status_code}: {resp.text[:200]}"
        )

    try:
        payload = resp.json()
    except Exception as err:  # noqa: BLE001
        raise YellowGridApiError(f"Could not decode JSON: {err}") from err

    # The sliding-session renewal: harvest the fresh cookie the server just
    # minted for us. curl_cffi exposes Set-Cookie values via resp.cookies.
    renewed = resp.cookies.get("userToken")

    return parse_earnings(payload, delivery_day, device_id), renewed


__all__ = (
    "YellowGridAuthError",
    "YellowGridApiError",
    "async_fetch_earnings",
    "parse_earnings",
    "day_bounds_ms",
)