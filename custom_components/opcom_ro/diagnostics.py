"""Diagnostics support.

Adds a one-click "Download diagnostics" action to the integration's
config-entry menu (Devices & Services → OPCOM Romania → ⋮ → Download
diagnostics). The resulting JSON file is what a user can send for
troubleshooting. It contains no personal data — only configuration and a
redacted summary of the fetched market data.
"""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_CURRENCY, CONF_RESOLUTIONS
from homeassistant.core import HomeAssistant

from .const import CONF_ENABLE_DEBUG_LOG, CONF_WINDOW_MINUTES, CONF_NUM_WINDOWS, DOMAIN
from .coordinator import OpcomCoordinator
from .models import DayResult


def _summarize_day(day: DayResult | None) -> dict[str, Any] | None:
    if not day or not day.has_data:
        return None
    prices = [i.price for i in day.intervals]
    return {
        "delivery_day": day.delivery_day.isoformat(),
        "interval_count": len(day.intervals),
        "base_price": day.base_price,
        "peak_price": day.peak_price,
        "off_peak_price": day.off_peak_price,
        "average_price": round(sum(prices) / len(prices), 2) if prices else None,
        "min_price": round(min(prices), 2) if prices else None,
        "max_price": round(max(prices), 2) if prices else None,
        "first_3_prices": [round(p, 2) for p in prices[:3]],
        "last_3_prices": [round(p, 2) for p in prices[-3:]],
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics information for a config entry."""
    coordinator: OpcomCoordinator = hass.data[DOMAIN][entry.entry_id]
    data = coordinator.data or {}

    return {
        "entry": {
            "title": entry.title,
            "version": entry.version,
            "options": dict(entry.options),
            "data": {
                CONF_CURRENCY: entry.data.get(CONF_CURRENCY),
                CONF_RESOLUTIONS: entry.data.get(CONF_RESOLUTIONS),
                CONF_WINDOW_MINUTES: entry.data.get(CONF_WINDOW_MINUTES),
                CONF_NUM_WINDOWS: entry.data.get(CONF_NUM_WINDOWS),
                CONF_ENABLE_DEBUG_LOG: entry.data.get(CONF_ENABLE_DEBUG_LOG),
            },
        },
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "last_exception": str(coordinator.last_exception)
            if coordinator.last_exception
            else None,
            "update_interval": str(coordinator.update_interval),
            "today_date": coordinator.today_date.isoformat(),
            "debug_log_enabled": coordinator.file_log.enabled,
            "today": _summarize_day(data.get("today")),
            "tomorrow": _summarize_day(data.get("tomorrow")),
        },
    }