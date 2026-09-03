"""Constants and configuration model for the OPCOM Romania integration."""
from __future__ import annotations

from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

DOMAIN = "opcom_ro"
PLATFORMS = ["sensor", "binary_sensor", "button"]

# OPCOM publishes day-ahead results in Romanian market time (Europe/Bucharest).
# Interval 1 always starts at 00:00 market-local on the delivery day.
MARKET_TZ = ZoneInfo("Europe/Bucharest")

# We always fetch the native 15-minute granularity (96 intervals/day) and
# aggregate locally to 30/60 minutes. The `resolution` query parameter on the
# OPCOM export endpoint is currently ignored by the server (it always returns
# 96 PT15M rows), so fetching PT15M is the only reliable source of truth.
OPCOM_URL_TEMPLATE = (
    "https://www.opcom.ro/rapoarte-pzu-raportPIP-export-csv/{date}/{lang}"
    "?resolution=PT15M"
)

# --- Config keys -----------------------------------------------------------
CONF_CURRENCY = "currency"
CONF_RESOLUTIONS = "resolutions"
CONF_REFRESH_INTERVAL = "refresh_interval"
CONF_WINDOW_MINUTES = "window_minutes"
CONF_NUM_WINDOWS = "num_windows"
CONF_LOW_THRESHOLD = "low_threshold"
CONF_HIGH_THRESHOLD = "high_threshold"
CONF_PERCENTILE_LOW = "percentile_low"
CONF_PERCENTILE_HIGH = "percentile_high"
CONF_ENABLE_DEBUG_LOG = "enable_debug_log"

# Debug log file (written to the HA config directory when enabled).
DEBUG_LOG_FILENAME = "opcom_ro_debug.log"

# --- Currency / language mapping ------------------------------------------
CURRENCY_RON = "RON"
CURRENCY_EUR = "EUR"
CURRENCY_TO_LANG: dict[str, str] = {CURRENCY_RON: "ro", CURRENCY_EUR: "en"}
CURRENCY_TO_UNIT: dict[str, str] = {CURRENCY_RON: "lei/MWh", CURRENCY_EUR: "EUR/MWh"}

# --- Resolutions -----------------------------------------------------------
RESOLUTIONS: dict[str, int] = {"PT15M": 15, "PT30M": 30, "PT60M": 60}

# --- Defaults --------------------------------------------------------------
DEFAULT_CURRENCY = CURRENCY_RON
DEFAULT_RESOLUTIONS = ["PT15M"]
DEFAULT_REFRESH_INTERVAL = 5
DEFAULT_WINDOW_MINUTES = 60
DEFAULT_NUM_WINDOWS = 3
DEFAULT_PERCENTILE_LOW = 25
DEFAULT_PERCENTILE_HIGH = 75
DEFAULT_ENABLE_DEBUG_LOG = False

# OPCOM publishes next-day results between roughly 13:00 and 15:00 market time.
PUBLISH_HINT = "OPCOM publica rezultatele pentru ziua urmatoare intre 13:00-15:00 (ora Romaniei)."


@dataclass
class OpcomConfig:
    """Runtime configuration derived from a config entry."""

    currency: str = DEFAULT_CURRENCY
    resolutions: list[str] = field(default_factory=lambda: list(DEFAULT_RESOLUTIONS))
    refresh_interval: int = DEFAULT_REFRESH_INTERVAL
    window_minutes: int = DEFAULT_WINDOW_MINUTES
    num_windows: int = DEFAULT_NUM_WINDOWS
    low_threshold: float | None = None
    high_threshold: float | None = None
    percentile_low: int = DEFAULT_PERCENTILE_LOW
    percentile_high: int = DEFAULT_PERCENTILE_HIGH
    enable_debug_log: bool = DEFAULT_ENABLE_DEBUG_LOG

    @property
    def lang(self) -> str:
        """OPCOM data language implied by the chosen currency."""
        return CURRENCY_TO_LANG[self.currency]

    @property
    def unit(self) -> str:
        """Unit of measurement implied by the chosen currency."""
        return CURRENCY_TO_UNIT[self.currency]

    @classmethod
    def from_entry(cls, entry_data: dict) -> "OpcomConfig":
        def _threshold(key) -> float | None:
            val = entry_data.get(key)
            # 0 / "" / None all mean "not configured".
            if val in (None, "", 0):
                return None
            return float(val)

        return cls(
            currency=entry_data.get(CONF_CURRENCY, DEFAULT_CURRENCY),
            resolutions=entry_data.get(CONF_RESOLUTIONS, list(DEFAULT_RESOLUTIONS)),
            refresh_interval=entry_data.get(CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL),
            window_minutes=entry_data.get(CONF_WINDOW_MINUTES, DEFAULT_WINDOW_MINUTES),
            num_windows=entry_data.get(CONF_NUM_WINDOWS, DEFAULT_NUM_WINDOWS),
            low_threshold=_threshold(CONF_LOW_THRESHOLD),
            high_threshold=_threshold(CONF_HIGH_THRESHOLD),
            percentile_low=entry_data.get(CONF_PERCENTILE_LOW, DEFAULT_PERCENTILE_LOW),
            percentile_high=entry_data.get(CONF_PERCENTILE_HIGH, DEFAULT_PERCENTILE_HIGH),
            enable_debug_log=bool(entry_data.get(CONF_ENABLE_DEBUG_LOG, DEFAULT_ENABLE_DEBUG_LOG)),
        )