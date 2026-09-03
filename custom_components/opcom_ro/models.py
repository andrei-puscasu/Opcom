"""Data models for parsed OPCOM day-ahead market results."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List


@dataclass
class Interval:
    """A single native 15-minute market interval."""

    index: int  # 1..96
    start: datetime  # tz-aware, Europe/Bucharest
    price: float  # per MWh, in the selected currency
    volume: float  # MWh
    buy_volume: float  # MWh
    sell_volume: float  # MWh


@dataclass
class DayResult:
    """All 96 native intervals for one delivery day, plus OPCOM summary rows."""

    delivery_day: date
    intervals: List[Interval] = field(default_factory=list)
    base_price: float | None = None
    peak_price: float | None = None
    off_peak_price: float | None = None

    @property
    def has_data(self) -> bool:
        return bool(self.intervals)

    @property
    def average_price(self) -> float | None:
        if not self.intervals:
            return None
        return sum(i.price for i in self.intervals) / len(self.intervals)


@dataclass
class AggregatedInterval:
    """An interval at a coarser resolution (30/60 min), averaged from PT15M."""

    index: int  # 1..N for the target resolution
    start: datetime  # tz-aware, Europe/Bucharest
    end: datetime  # tz-aware, Europe/Bucharest (exclusive)
    price: float  # average lei/MWh or EUR/MWh across the native sub-intervals
    volume: float  # summed MWh across the native sub-intervals


@dataclass
class Window:
    """A contiguous optimal window selected by the sliding-window algorithm."""

    start_idx: int  # 0-based index into the aggregated interval list
    end_idx: int  # exclusive
    avg_price: float
    intervals: List[AggregatedInterval] = field(default_factory=list)

    @property
    def start(self) -> datetime:
        return self.intervals[0].start

    @property
    def end(self) -> datetime:
        return self.intervals[-1].end

    @property
    def duration_minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)