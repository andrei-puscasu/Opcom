"""Pure functions: aggregation, optimal-window selection, percentile, time helpers.

All time reasoning is done in the OPCOM market timezone (Europe/Bucharest) so
that "current interval" matches the delivery day regardless of the Home
Assistant server's local timezone. Display helpers format times as HH:MM in
market-local time; conversion to the HA timezone for UI is left to the
frontend.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable, List

from .const import MARKET_TZ
from .models import AggregatedInterval, DayResult, Window


def now_market() -> datetime:
    """Current moment in the OPCOM market timezone."""
    return datetime.now(MARKET_TZ)


# --- Aggregation -----------------------------------------------------------

def aggregate(day: DayResult | None, res_minutes: int) -> List[AggregatedInterval]:
    """Aggregate native 15-minute intervals into coarser resolution intervals.

    Prices are averaged and volumes summed across each block of
    ``res_minutes // 15`` native intervals.
    """
    if not day or not day.has_data:
        return []

    step = max(1, res_minutes // 15)
    out: list[AggregatedInterval] = []
    idx = 1
    native = day.intervals
    for i in range(0, len(native), step):
        chunk = native[i : i + step]
        if not chunk:
            break
        avg_price = sum(x.price for x in chunk) / len(chunk)
        volume = sum(x.volume for x in chunk)
        start = chunk[0].start
        end = chunk[-1].start + timedelta(minutes=15)
        out.append(
            AggregatedInterval(index=idx, start=start, end=end, price=avg_price, volume=volume)
        )
        idx += 1
    return out


def resolution_of(aggregated: List[AggregatedInterval]) -> int:
    """Infer the resolution (minutes) of an aggregated list, defaulting to 15."""
    if len(aggregated) >= 2:
        delta = aggregated[1].start - aggregated[0].start
        return int(delta.total_seconds() // 60)
    return 15


# --- Current / next interval ----------------------------------------------

def current_and_next(
    aggregated: List[AggregatedInterval], now_dt: datetime | None = None
) -> tuple[AggregatedInterval | None, AggregatedInterval | None]:
    """Return the interval containing ``now`` and the one that follows it."""
    if not aggregated:
        return None, None
    if now_dt is None:
        now_dt = now_market()

    for j, ai in enumerate(aggregated):
        if ai.start <= now_dt < ai.end:
            nxt = aggregated[j + 1] if j + 1 < len(aggregated) else None
            return ai, nxt

    if now_dt >= aggregated[-1].end:
        return aggregated[-1], None
    return aggregated[0], aggregated[1] if len(aggregated) > 1 else None


# --- Optimal window selection ---------------------------------------------

def compute_windows(
    aggregated: List[AggregatedInterval],
    window_minutes: int,
    num_windows: int,
    mode: str,
) -> List[Window]:
    """Select ``num_windows`` non-overlapping windows of ``window_minutes``.

    A sliding window computes the average price for every possible position.
    Candidates are sorted (cheapest first for ``cheap``, most expensive first
    for ``expensive``) and chosen greedily, skipping any candidate that
    overlaps an already-chosen window. ``window_minutes`` is rounded to the
    nearest whole number of resolution intervals (minimum one).
    """
    n = len(aggregated)
    if n == 0 or num_windows <= 0:
        return []

    res_min = resolution_of(aggregated)
    win = max(1, round(window_minutes / res_min))
    if win > n:
        win = n

    candidates: list[tuple[float, int, int]] = []
    for s in range(0, n - win + 1):
        e = s + win
        avg = sum(aggregated[k].price for k in range(s, e)) / win
        candidates.append((avg, s, e))

    if mode == "cheap":
        candidates.sort(key=lambda c: (c[0], c[1]))
    else:  # expensive
        candidates.sort(key=lambda c: (-c[0], c[1]))

    chosen: list[Window] = []
    occupied = [False] * n
    for avg, s, e in candidates:
        if any(occupied[k] for k in range(s, e)):
            continue
        chosen.append(
            Window(start_idx=s, end_idx=e, avg_price=avg, intervals=aggregated[s:e])
        )
        for k in range(s, e):
            occupied[k] = True
        if len(chosen) >= num_windows:
            break
    return chosen


def in_any_window(current: AggregatedInterval | None, windows: Iterable[Window]) -> bool:
    """Whether the current interval (1-based index) falls inside any window."""
    if current is None:
        return False
    zero_based = current.index - 1
    return any(w.start_idx <= zero_based < w.end_idx for w in windows)


# --- Percentile ------------------------------------------------------------

def percentile_rank(value: float, values: Iterable[float]) -> float | None:
    """Mid-rank percentile of ``value`` within ``values`` (0..100)."""
    s = sorted(values)
    if not s:
        return None
    below = sum(1 for v in s if v < value)
    equal = sum(1 for v in s if v == value)
    return (below + equal / 2.0) / len(s) * 100.0


# --- Formatting / attributes ----------------------------------------------

def price_curve(aggregated: List[AggregatedInterval]) -> dict[str, float]:
    """Map ``HH:MM`` (market-local start) -> rounded price, for charting."""
    return {ai.start.strftime("%H:%M"): round(ai.price, 2) for ai in aggregated}


def windows_to_dicts(windows: Iterable[Window]) -> list[dict]:
    """Serialize windows for entity extra state attributes."""
    return [
        {
            "start": w.start.strftime("%H:%M"),
            "end": w.end.strftime("%H:%M"),
            "avg_price": round(w.avg_price, 2),
            "duration_min": w.duration_minutes,
        }
        for w in windows
    ]


def remaining_count(aggregated: List[AggregatedInterval], windows: Iterable[Window]) -> int:
    """Count intervals inside selected windows that have not yet elapsed."""
    now_dt = now_market()
    win_intervals = set()
    for w in windows:
        for k in range(w.start_idx, w.end_idx):
            win_intervals.add(k)
    if not win_intervals:
        return 0
    current, _ = current_and_next(aggregated, now_dt)
    if current is None:
        return len(win_intervals)
    current_zero = current.index - 1
    return sum(1 for k in win_intervals if k >= current_zero)