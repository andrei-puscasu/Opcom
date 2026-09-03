"""Data update coordinator for OPCOM day-ahead results.

Fetches today's and tomorrow's delivery-day results on a configurable poll
interval. OPCOM only publishes once per day (~13:00-15:00 market time), but we
re-fetch on the poll interval so the "current interval" derivation and binary
sensors stay fresh; the payload is tiny and the endpoint is public.

Retry with exponential backoff is applied per day. On failure we keep the
previous successful data for that day so entities keep working instead of
flapping to unavailable.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import async_fetch_day
from .const import DOMAIN
from .helpers import now_market
from .logger import OpcomFileLogger
from .models import DayResult

_LOGGER = logging.getLogger(__name__)

_MAX_ATTEMPTS = 3
_DAYS_AHEAD = 1  # today + tomorrow


class OpcomCoordinator(DataUpdateCoordinator):
    """Coordinates fetching OPCOM day-ahead results for today and tomorrow."""

    def __init__(self, hass: HomeAssistant, config) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=max(1, config.refresh_interval)),
        )
        self.config = config
        self.file_log = OpcomFileLogger(hass, enabled=config.enable_debug_log)
        if config.enable_debug_log:
            self.file_log.enable()
        # previous successful data, keyed by delivery date, for retry fallback
        self._cache: dict[date, DayResult | None] = {}

    @property
    def today_date(self) -> date:
        """The delivery day that is currently in progress (market-local)."""
        return now_market().date()

    @property
    def tomorrow_date(self) -> date:
        return self.today_date + timedelta(days=1)

    def get_day(self, which: str) -> DayResult | None:
        """Return the cached DayResult for ``today`` or ``tomorrow``."""
        if not self.data:
            return None
        return self.data.get(which)

    async def _fetch_one(self, delivery_day: date) -> DayResult | None:
        """Fetch a single delivery day with retry/backoff.

        Falls back to the previous cached value for that day on total failure.
        """
        last_exc: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                result = await async_fetch_day(self.hass, delivery_day, self.config.lang)
                self._cache[delivery_day] = result
                self.file_log.log(
                    "debug",
                    "Fetched %s (lang=%s): %s intervals",
                    delivery_day,
                    self.config.lang,
                    len(result.intervals) if result else 0,
                )
                return result
            except Exception as err:  # noqa: BLE001 - network/HTTP errors
                last_exc = err
                self.file_log.log(
                    "warning",
                    "Fetch attempt %d/%d for %s failed: %s",
                    attempt + 1,
                    _MAX_ATTEMPTS,
                    delivery_day,
                    err,
                )
                if attempt < _MAX_ATTEMPTS - 1:
                    await asyncio.sleep(2 ** attempt)
        _LOGGER.warning(
            "OPCOM fetch failed for %s after %d attempts: %s",
            delivery_day,
            _MAX_ATTEMPTS,
            last_exc,
        )
        # Prefer previously known data; otherwise mark as not-yet-published.
        if delivery_day in self._cache:
            return self._cache[delivery_day]
        return None

    async def _async_update_data(self) -> dict[str, Any]:
        today = self.today_date
        dates = [today + timedelta(days=offset) for offset in range(_DAYS_AHEAD + 1)]

        days: dict[date, DayResult | None] = {}
        had_any = False
        for delivery_day in dates:
            result = await self._fetch_one(delivery_day)
            days[delivery_day] = result
            if result is not None:
                had_any = True

        self.file_log.log(
            "info",
            "Update done: today=%s intervals, tomorrow=%s intervals",
            len(days[today].intervals) if days.get(today) else 0,
            len(days[self.tomorrow_date].intervals) if days.get(self.tomorrow_date) else 0,
        )

        if not had_any and not self.data:
            # First run and nothing published at all -> surface the error.
            raise UpdateFailed("No OPCOM data available for today or tomorrow")

        return {
            "today_date": today,
            "tomorrow_date": self.tomorrow_date,
            "today": days.get(today),
            "tomorrow": days.get(self.tomorrow_date),
            "days": days,
        }