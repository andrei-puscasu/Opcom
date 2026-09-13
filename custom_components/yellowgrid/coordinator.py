"""Data update coordinator for YellowGrid earnings.

Polls the authenticated ``earnings`` endpoint for the current delivery day on
a configurable interval. Each successful poll returns a fresh ``userToken``
(sliding session); the coordinator persists it via the HA Store so the session
stays alive across restarts without any user interaction.

Failure handling:
  * :class:`ConfigEntryAuthFailed` on HTTP 401 -> HA starts the reauth flow so
    the user can paste a fresh cookie. Sensors go unavailable meanwhile.
  * :class:`UpdateFailed` on transient errors -> the coordinator keeps the last
    good data and retries on the next poll (HA's standard backoff).
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import YellowGridApiError, YellowGridAuthError, async_fetch_earnings
from .const import DEFAULT_REFRESH_INTERVAL, DOMAIN, MARKET_TZ, YellowGridConfig
from .models import YGEarnings

_LOGGER = logging.getLogger(__name__)


def _now_market():
    from datetime import datetime

    return datetime.now(MARKET_TZ)


class YellowGridCoordinator(DataUpdateCoordinator):
    """Coordinates fetching YellowGrid earnings for the current delivery day."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        config: YellowGridConfig,
        current_token: str,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(
                minutes=max(1, config.refresh_interval or DEFAULT_REFRESH_INTERVAL)
            ),
        )
        self._entry = entry
        self.config = config
        self._token = current_token
        self._last_earnings: YGEarnings | None = None

    # -- token management ---------------------------------------------------

    @property
    def token(self) -> str:
        """The current session token (renewed on each successful poll)."""
        return self._token

    async def _persist_token(self, token: str) -> None:
        """Persist a renewed token to the HA Store."""
        # Local import to avoid a circular import at module load.
        from . import async_save_token

        if token and token != self._token:
            self._token = token
            await async_save_token(self.hass, self._entry, token)
            _LOGGER.debug("Session token renewed and persisted")

    # -- helpers ------------------------------------------------------------

    @property
    def today_date(self) -> date:
        """The delivery day currently in progress (market-local)."""
        return _now_market().date()

    def current_interval_index(self) -> int:
        """1-based index (1..96) of the 15-min slot currently in progress."""
        now = _now_market()
        return max(1, min(96, (now.hour * 60 + now.minute) // 15 + 1))

    def get_earnings(self) -> YGEarnings | None:
        """The most recent successfully fetched earnings (today)."""
        return self._last_earnings

    # -- update -------------------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        day = self.today_date
        try:
            earnings, renewed = await async_fetch_earnings(
                self._token, self.config.device_id, day
            )
        except YellowGridAuthError as err:
            # Token expired/revoked: surface to HA's reauth machinery.
            raise ConfigEntryAuthFailed(str(err)) from err
        except YellowGridApiError as err:
            # Transient: keep last good data if we have it, else fail up.
            _LOGGER.warning("YellowGrid fetch failed: %s", err)
            if self._last_earnings is not None:
                raise UpdateFailed(str(err)) from err
            raise

        if renewed:
            await self._persist_token(renewed)

        self._last_earnings = earnings
        _LOGGER.debug(
            "YellowGrid update ok: day=%s intervals=%d export=%s kWh earnings=%s lei",
            day,
            len(earnings.intervals),
            earnings.total_export,
            earnings.total_earnings,
        )
        return {
            "delivery_day": day,
            "earnings": earnings,
            "current_index": self.current_interval_index(),
        }