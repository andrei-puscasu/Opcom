"""Sensor platform for OPCOM Romania day-ahead prices.

For each configured resolution a set of sensors is created:

* current_price / next_price      - the price of the current/next interval
* average_today / average_tomorrow - daily average + OPCOM Base/Peak/Off-Peak
* cheapest/expensive _today/_tomorrow - optimal windows (sliding-window algo)
* percentile_now                   - current price's rank in today's distribution

The today price curve is exposed as the ``prices`` attribute on
``current_price`` and the tomorrow curve on ``average_tomorrow`` so it can be
plotted directly with a chart card.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, RESOLUTIONS, OpcomConfig
from .coordinator import OpcomCoordinator
from .helpers import (
    aggregate,
    compute_windows,
    current_and_next,
    percentile_rank,
    price_curve,
    remaining_count,
    windows_to_dicts,
)
from .models import DayResult

# Kinds that derive from tomorrow's (not-yet-published) data.
_TOMORROW_KINDS = {
    "average_tomorrow",
    "cheapest_tomorrow",
    "expensive_tomorrow",
}


@dataclass
class OpcomSensorDescription(SensorEntityDescription):
    """Sensor entity description with a behaviour ``kind``."""

    kind: str = ""


SENSORS: tuple[OpcomSensorDescription, ...] = (
    OpcomSensorDescription(
        key="current_price",
        translation_key="current_price",
        kind="current_price",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:cash",
        suggested_display_precision=2,
    ),
    OpcomSensorDescription(
        key="next_price",
        translation_key="next_price",
        kind="next_price",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:cash-clock",
        suggested_display_precision=2,
    ),
    OpcomSensorDescription(
        key="average_today",
        translation_key="average_today",
        kind="average_today",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:chart-line",
        suggested_display_precision=2,
    ),
    OpcomSensorDescription(
        key="average_tomorrow",
        translation_key="average_tomorrow",
        kind="average_tomorrow",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:chart-line-variant",
        suggested_display_precision=2,
    ),
    OpcomSensorDescription(
        key="cheapest_today",
        translation_key="cheapest_today",
        kind="cheapest_today",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:arrow-down-bold-box",
        suggested_display_precision=2,
    ),
    OpcomSensorDescription(
        key="expensive_today",
        translation_key="expensive_today",
        kind="expensive_today",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:arrow-up-bold-box",
        suggested_display_precision=2,
    ),
    OpcomSensorDescription(
        key="cheapest_tomorrow",
        translation_key="cheapest_tomorrow",
        kind="cheapest_tomorrow",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:arrow-down-bold-box-outline",
        suggested_display_precision=2,
    ),
    OpcomSensorDescription(
        key="expensive_tomorrow",
        translation_key="expensive_tomorrow",
        kind="expensive_tomorrow",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:arrow-up-bold-box-outline",
        suggested_display_precision=2,
    ),
    OpcomSensorDescription(
        key="percentile_now",
        translation_key="percentile_now",
        kind="percentile_now",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:percent",
        suggested_display_precision=0,
    ),
)


class OpcomEntity(CoordinatorEntity[OpcomCoordinator]):
    """Common base: device grouping, unique id, currency unit."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: OpcomCoordinator, entry: ConfigEntry, res: str) -> None:
        super().__init__(coordinator)
        self.coordinator = coordinator
        self._entry = entry
        self._res = res
        self._attr_unique_id = f"{entry.entry_id}_{res}_{self.entity_description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{entry.entry_id}_{res}")},
            "name": f"OPCOM Romania {RESOLUTIONS[res]} min",
            "manufacturer": "OPCOM",
            "model": "Day-Ahead Market (PZU)",
        }


class OpcomSensor(OpcomEntity, SensorEntity):
    """A single OPCOM price/window sensor."""

    entity_description: OpcomSensorDescription

    def __init__(
        self,
        coordinator: OpcomCoordinator,
        entry: ConfigEntry,
        res: str,
        description: OpcomSensorDescription,
    ) -> None:
        self.entity_description = description
        super().__init__(coordinator, entry, res)
        config: OpcomConfig = coordinator.config
        if description.kind == "percentile_now":
            self._attr_native_unit_of_measurement = "%"
        else:
            self._attr_native_unit_of_measurement = config.unit

    # -- helpers ------------------------------------------------------------

    @property
    def _config(self) -> OpcomConfig:
        return self.coordinator.config

    @property
    def _res_minutes(self) -> int:
        return RESOLUTIONS[self._res]

    def _day(self, which: str) -> DayResult | None:
        return self.coordinator.get_day(which)

    def _uses_tomorrow(self) -> bool:
        return self.entity_description.kind in _TOMORROW_KINDS

    def _agg(self, which: str):
        day = self._day(which)
        return aggregate(day, self._res_minutes)

    # -- availability -------------------------------------------------------

    @property
    def available(self) -> bool:
        if not self.coordinator.last_update_success:
            return False
        which = "tomorrow" if self._uses_tomorrow() else "today"
        day = self._day(which)
        return day is not None and day.has_data

    # -- value / attributes -------------------------------------------------

    @property
    def native_value(self) -> float | None:
        kind = self.entity_description.kind
        if kind == "current_price":
            cur, _ = current_and_next(self._agg("today"))
            return cur.price if cur else None
        if kind == "next_price":
            _, nxt = current_and_next(self._agg("today"))
            return nxt.price if nxt else None
        if kind == "average_today":
            return self._day("today").average_price
        if kind == "average_tomorrow":
            day = self._day("tomorrow")
            return day.average_price if day else None
        if kind in ("cheapest_today", "cheapest_tomorrow"):
            which = "tomorrow" if kind == "cheapest_tomorrow" else "today"
            windows = compute_windows(self._agg(which), self._config.window_minutes, self._config.num_windows, "cheap")
            return windows[0].avg_price if windows else None
        if kind in ("expensive_today", "expensive_tomorrow"):
            which = "tomorrow" if kind == "expensive_tomorrow" else "today"
            windows = compute_windows(self._agg(which), self._config.window_minutes, self._config.num_windows, "expensive")
            return windows[0].avg_price if windows else None
        if kind == "percentile_now":
            agg = self._agg("today")
            cur, _ = current_and_next(agg)
            if not cur:
                return None
            rank = percentile_rank(cur.price, [a.price for a in agg])
            return round(rank, 1) if rank is not None else None
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        kind = self.entity_description.kind
        cfg = self._config

        if kind == "current_price":
            agg = self._agg("today")
            cur, _ = current_and_next(agg)
            if not cur:
                return None
            return {
                "interval_index": cur.index,
                "interval_start": cur.start.isoformat(),
                "interval_end": cur.end.isoformat(),
                "volume_mwh": round(cur.volume, 2),
                "resolution": self._res,
                "prices": price_curve(agg),
            }

        if kind == "next_price":
            agg = self._agg("today")
            _, nxt = current_and_next(agg)
            if not nxt:
                return None
            return {
                "interval_index": nxt.index,
                "interval_start": nxt.start.isoformat(),
                "interval_end": nxt.end.isoformat(),
                "resolution": self._res,
            }

        if kind in ("average_today", "average_tomorrow"):
            which = "tomorrow" if kind == "average_tomorrow" else "today"
            day = self._day(which)
            if not day:
                return None
            attrs: dict[str, Any] = {
                "delivery_day": day.delivery_day.isoformat(),
                "base_price": day.base_price,
                "peak_price": day.peak_price,
                "off_peak_price": day.off_peak_price,
                "resolution": self._res,
            }
            if kind == "average_tomorrow":
                attrs["prices"] = price_curve(self._agg(which))
            return attrs

        if kind in ("cheapest_today", "expensive_today", "cheapest_tomorrow", "expensive_tomorrow"):
            which = "tomorrow" if "tomorrow" in kind else "today"
            mode = "cheap" if "cheapest" in kind else "expensive"
            agg = self._agg(which)
            windows = compute_windows(agg, cfg.window_minutes, cfg.num_windows, mode)
            attrs = {
                "windows": windows_to_dicts(windows),
                "window_minutes": cfg.window_minutes,
                "num_windows": cfg.num_windows,
                "resolution": self._res,
                "delivery_day": self._day(which).delivery_day.isoformat(),
            }
            if which == "today":
                attrs["remaining_intervals"] = remaining_count(agg, windows)
            return attrs

        if kind == "percentile_now":
            agg = self._agg("today")
            cur, _ = current_and_next(agg)
            if not cur:
                return None
            return {
                "current_price": round(cur.price, 2),
                "percentile_low": cfg.percentile_low,
                "percentile_high": cfg.percentile_high,
                "resolution": self._res,
            }

        return None

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up OPCOM sensors for each configured resolution."""
    coordinator: OpcomCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[OpcomSensor] = []
    for res in sorted(coordinator.config.resolutions, key=lambda r: RESOLUTIONS[r]):
        for description in SENSORS:
            entities.append(OpcomSensor(coordinator, entry, res, description))
    async_add_entities(entities)