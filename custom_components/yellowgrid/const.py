"""Constants and configuration model for the YellowGrid integration.

YellowGrid (yellowgrid.ro) is a Romanian prosumer electricity supplier. Each
prosumer is billed per 15-minute interval with two prices:

* ``importPrice``  - what you pay to consume from the grid (a flat retail
  tariff, ~1.31 lei/kWh, essentially wholesale-independent).
* ``exportPrice``  - what you earn for injecting surplus PV (varies through
  the day, roughly tracking the OPCOM PZU day-ahead curve).

Prices are **account-specific** (personalised) and only available behind the
authenticated customer portal. Auth is a same-origin ``userToken`` httpOnly
session cookie; there is no bearer token or public endpoint. See
``api.py`` for how the session is kept alive.
"""
from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import ZoneInfo

DOMAIN = "yellowgrid"
PLATFORMS = ["sensor", "button"]

# YellowGrid bills in Romanian market time (Europe/Bucharest). Interval 1 is
# always 00:00 market-local on the delivery day; 96 intervals of 15 min each.
MARKET_TZ = ZoneInfo("Europe/Bucharest")

# Authenticated earnings endpoint. ``deviceId`` is the plant UUID; ``filter``
# is "day"; ``startTime``/``endTime`` are epoch-ms [start, end) of a
# midnight-to-midnight day in Europe/Bucharest.
YG_URL = "https://www.yellowgrid.ro/api/core-platform/earnings"
YG_REFERER = "https://www.yellowgrid.ro/dashboard/plant"
IMPERSONATE = "chrome"  # curl_cffi alias; impersonate Chrome TLS handshake

# --- Config keys -----------------------------------------------------------
CONF_USER_TOKEN = "user_token"  # the `userToken` cookie value (URL-encoded blob)
CONF_DEVICE_ID = "device_id"  # the plant UUID
CONF_REFRESH_INTERVAL = "refresh_interval"

# --- Defaults --------------------------------------------------------------
DEFAULT_REFRESH_INTERVAL = 15  # minutes; well under the token's idle-expiry

# One day in milliseconds (used to build the [startTime, endTime) window).
DAY_MS = 86_400_000

# Token persistence (HA Store key namespace). The cookie rotates on every
# authenticated request (sliding session); the latest value is persisted here
# so it survives restarts. ``entry.data`` holds the user's initial paste as a
# fallback.
STORAGE_VERSION = 1


@dataclass
class YellowGridConfig:
    """Runtime configuration derived from a config entry."""

    user_token: str = ""
    device_id: str = ""
    refresh_interval: int = DEFAULT_REFRESH_INTERVAL

    @classmethod
    def from_entry(cls, entry_data: dict) -> "YellowGridConfig":
        return cls(
            user_token=entry_data.get(CONF_USER_TOKEN, "") or "",
            device_id=entry_data.get(CONF_DEVICE_ID, "") or "",
            refresh_interval=int(
                entry_data.get(CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL)
            ),
        )