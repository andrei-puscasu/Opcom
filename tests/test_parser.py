"""Offline tests for the OPCOM CSV parser (no network, no Home Assistant).

Uses a baked-in sample that mirrors the real OPCOM export format (Romanian
source, lei/MWh, 96 PT15M intervals + summary rows). A tiny stub for the
handful of ``homeassistant.*`` modules imported at package init lets the
submodules import without a Home Assistant installation.
"""
import sys
import types
import unittest
from datetime import date, datetime, timedelta

# --- Minimal Home Assistant stubs (only what package __init__ imports) -----
if "homeassistant" not in sys.modules:
    def _make(name, **attrs):
        m = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        sys.modules[name] = m
        return m

    _make("homeassistant")
    _make("homeassistant.config_entries", ConfigEntry=type("ConfigEntry", (), {}))
    _make("homeassistant.core", HomeAssistant=type("HomeAssistant", (), {}))
    _make("homeassistant.helpers")
    _make(
        "homeassistant.helpers.update_coordinator",
        DataUpdateCoordinator=type("DataUpdateCoordinator", (), {}),
        UpdateFailed=type("UpdateFailed", (Exception,), {}),
    )
    _make("homeassistant.util")
    _dt = types.ModuleType("homeassistant.util.dt")
    _dt.now = lambda: datetime.now()  # not called in offline tests
    sys.modules["homeassistant.util.dt"] = _dt

from custom_components.opcom_ro.api import parse_csv  # noqa: E402
from custom_components.opcom_ro.const import MARKET_TZ  # noqa: E402
from custom_components.opcom_ro.helpers import (  # noqa: E402
    aggregate,
    compute_windows,
    percentile_rank,
)
from custom_components.opcom_ro.models import DayResult, Interval  # noqa: E402

SAMPLE_RO = """\"PIP si volum tranzactionat pentru ziua de livrare: 02/09/2026\"

\"\",\"Pret mediu [lei/MWh]\",\"Volum [MWh]\",\"Rezolutie\"
\"ROPEX_DAM_Base (1-24)\",\"1000.00\",\"40000.0\",\"PT15M\"
\"ROPEX_DAM_Peak (33-80)\",\"900.00\",\"21000.0\",\"PT15M\"
\"ROPEX_DAM_Off_Peak (1-32) & (81-96)\",\"1100.00\",\"19000.0\",\"PT15M\"

\"Zona de tranzactionare\",\"Interval\",\"Pret de Inchidere a Pietei [lei/MWh]\",\"Volum Tranzactionat [MW]\",\"Volum Tranzactionat pe cumparare [MW]\",\"Volum Tranzactionat pe vanzare [MW]\",\"Rezolutie\"
\"Romania\",\"1\",\"500.00\",\"1000.0\",\"900.0\",\"1000.0\",\"PT15M\"
\"Romania\",\"2\",\"600.00\",\"1000.0\",\"900.0\",\"1000.0\",\"PT15M\"
\"Romania\",\"3\",\"700.00\",\"1000.0\",\"900.0\",\"1000.0\",\"PT15M\"
\"Romania\",\"4\",\"800.00\",\"1000.0\",\"900.0\",\"1000.0\",\"PT15M\"
\"Romania\",\"96\",\"900.00\",\"1000.0\",\"900.0\",\"1000.0\",\"PT15M\"
"""


def _synthetic_day(prices=None) -> DayResult:
    """A full 96-interval day; prices default to 1..96."""
    midnight = datetime(2026, 9, 2, tzinfo=MARKET_TZ)
    prices = prices or list(range(1, 97))
    intervals = [
        Interval(
            index=i + 1,
            start=midnight + timedelta(minutes=15 * i),
            price=float(prices[i]),
            volume=1.0,
            buy_volume=1.0,
            sell_volume=1.0,
        )
        for i in range(96)
    ]
    return DayResult(delivery_day=date(2026, 9, 2), intervals=intervals)


class ParserTests(unittest.TestCase):
    def test_parse_ro_intervals_and_summary(self):
        day = parse_csv(SAMPLE_RO, date(2026, 9, 2))
        self.assertIsNotNone(day)
        self.assertEqual(len(day.intervals), 5)  # only 5 Romania rows in sample
        self.assertEqual(day.intervals[0].price, 500.0)
        self.assertEqual(day.intervals[0].volume, 1000.0)
        self.assertEqual(day.intervals[0].start.hour, 0)
        self.assertEqual(day.base_price, 1000.0)
        self.assertEqual(day.peak_price, 900.0)
        self.assertEqual(day.off_peak_price, 1100.0)

    def test_empty_returns_none(self):
        self.assertIsNone(parse_csv("", date(2026, 9, 10)))
        self.assertIsNone(parse_csv("   \n  ", date(2026, 9, 10)))

    def test_aggregate_60min_averages_first_four(self):
        full = _synthetic_day()
        agg = aggregate(full, 60)
        self.assertEqual(len(agg), 24)
        # First hour = intervals 1..4 -> prices 1,2,3,4 -> avg 2.5
        self.assertAlmostEqual(agg[0].price, 2.5)

    def test_windows_non_overlapping_and_sorted(self):
        agg = aggregate(_synthetic_day([(i * 37) % 200 for i in range(96)]), 15)
        cheap = compute_windows(agg, window_minutes=60, num_windows=3, mode="cheap")
        self.assertEqual(len(cheap), 3)
        occupied = []
        for w in cheap:
            for k in range(w.start_idx, w.end_idx):
                self.assertNotIn(k, occupied)
                occupied.append(k)
        self.assertLessEqual(cheap[0].avg_price, cheap[1].avg_price)

    def test_percentile_rank(self):
        # value 5 in 1..10: 4 below, 1 equal -> mid-rank (4 + 0.5)/10*100 = 45.0
        self.assertEqual(percentile_rank(5, list(range(1, 11))), 45.0)
        self.assertIsNone(percentile_rank(1, []))


if __name__ == "__main__":
    unittest.main()