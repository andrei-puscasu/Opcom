"""Diagnostics support.

Adds a one-click "Download diagnostics" action to the integration's
config-entry menu. The downloaded JSON is safe to share: it contains
configuration and a redacted summary of the fetched earnings, and **never**
the ``userToken`` cookie (a real credential).
"""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_DEVICE_ID, CONF_REFRESH_INTERVAL, DOMAIN
from .coordinator import YellowGridCoordinator
from .models import YGEarnings


def _summarize(earnings: YGEarnings | None) -> dict[str, Any] | None:
    if not earnings or not earnings.has_data:
        return None
    import_prices = [round(iv.import_price, 4) for iv in earnings.intervals]
    export_prices = [round(iv.export_price, 4) for iv in earnings.intervals]
    return {
        "delivery_day": earnings.delivery_day.isoformat(),
        "device_id": earnings.device_id,
        "interval_count": len(earnings.intervals),
        "total_import_kwh": round(earnings.total_import, 3),
        "total_export_kwh": round(earnings.total_export, 3),
        "total_earnings_ron": round(earnings.total_earnings, 2),
        "total_savings_ron": round(earnings.total_savings, 2),
        "import_price_min": round(min(import_prices), 4),
        "import_price_max": round(max(import_prices), 4),
        "export_price_min": round(min(export_prices), 4),
        "export_price_max": round(max(export_prices), 4),
        "first_3_export_prices": export_prices[:3],
        "last_3_export_prices": export_prices[-3:],
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return redacted diagnostics for a config entry."""
    coordinator: YellowGridCoordinator = hass.data[DOMAIN][entry.entry_id]
    return {
        "entry": {
            "title": entry.title,
            "version": entry.version,
            "options": dict(entry.options),
            # Intentionally NO user_token. Only flag presence + a length hint.
            "data": {
                CONF_DEVICE_ID: entry.data.get(CONF_DEVICE_ID),
                CONF_REFRESH_INTERVAL: entry.data.get(CONF_REFRESH_INTERVAL),
                "user_token_present": bool(entry.data.get("user_token")),
                "user_token_length": len(entry.data.get("user_token") or ""),
            },
        },
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "last_exception": str(coordinator.last_exception)
            if coordinator.last_exception
            else None,
            "update_interval": str(coordinator.update_interval),
            "current_interval_index": coordinator.current_interval_index(),
            "earnings": _summarize(coordinator.get_earnings()),
        },
    }