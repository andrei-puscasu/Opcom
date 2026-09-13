"""Data models for parsed YellowGrid earnings responses."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import List


@dataclass
class YGInterval:
    """A single 15-minute interval (1..96) for a delivery day.

    All monetary fields are in lei (RON); energy fields are in kWh.
    """

    index: int  # 1..96
    import_price: float  # lei/kWh (with all taxes/charges)
    export_price: float  # lei/kWh (what you earn for surplus)
    import_price_without_tax: float  # lei/kWh (energy line only)
    import_price_tax: float  # lei/kWh (regulated charges + VAT)
    export: float  # kWh injected to the grid in this interval
    import_kwh: float  # kWh consumed from the grid in this interval
    savings: float  # lei saved by self-consumption
    earnings: float  # lei earned from export in this interval


@dataclass
class YGEarnings:
    """The full 96-interval earnings curve for one delivery day."""

    delivery_day: date
    device_id: str
    intervals: List[YGInterval] = field(default_factory=list)
    total_import: float = 0.0  # kWh
    total_export: float = 0.0  # kWh
    total_earnings: float = 0.0  # lei
    total_savings: float = 0.0  # lei

    @property
    def has_data(self) -> bool:
        return bool(self.intervals)

    def interval(self, index: int) -> YGInterval | None:
        """Return the interval with the given 1-based index, or None."""
        if not self.intervals:
            return None
        if index < 1 or index > len(self.intervals):
            return None
        return self.intervals[index - 1]