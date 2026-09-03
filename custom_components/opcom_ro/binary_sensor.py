"""Binary sensor platform for OPCOM-based automation signals.

For each configured resolution:

* should_charge_now    - ON when the current interval is inside one of the
                         cheapest windows (and optionally below low_threshold)
* should_discharge_now - ON when inside one of the most expensive windows
                         (and optionally above high_threshold)
* price_below_threshold / price_above_threshold - simple price gates
                         (only created when the matching threshold is set)
* cheap_percentile_now / expensive_percentile_now - rank-based gates using
                         today's price distribution

These are designed for battery charge/discharge, EV charging and heat-pump
automations: use ``should_charge_now`` to import power and
``should_discharge_now`` to export.
"""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_HIGH_THRESHOLD, CONF_LOW_THRESHOLD, DOMAIN, RESOLUTIONS, OpcomConfig
from .coordinator import OpcomCoordinator
from .helpers import (
    aggregate,
    compute_windows,
    current_and_next,
    in_any_window,
    percentile_rank,
)
from .sensor import OpcomEntity


@dataclass
class OpcomBinarySensorDescription(BinarySensorEntityDescription):
    """Binary sensor description with a behaviour ``kind``."""

    kind: str = ""


def _binary(key, kind, icon) -> OpcomBinarySensorDescription:
    return OpcomBinarySensorDescription(
        key=key,
        translation_key=key,
        kind=kind,
        icon=icon,
    )


# Always-on binary sensors (one per resolution).
BASE_BINARY: tuple[OpcomBinarySensorDescription, ...] = (
    _binary("should_charge_now", "should_charge_now", "mdi:battery-charging"),
    _binary("should_discharge_now", "should_discharge_now", "mdi:battery-arrow-up-outline"),
    _binary("cheap_percentile_now", "cheap_percentile_now", "mdi:arrow-down-thick"),
    _binary("expensive_percentile_now", "expensive_percentile_now", "mdi:arrow-up-thick"),
)

# Threshold-gated binary sensors (created only when the threshold is set).
LOW_THRESHOLD_BINARY = _binary(
    "price_below_threshold", "price_below_threshold", "mdi:arrow-down-circle-outline"
)
HIGH_THRESHOLD_BINARY = _binary(
    "price_above_threshold", "price_above_threshold", "mdi:arrow-up-circle-outline"
)


class OpcomBinarySensor(OpcomEntity, BinarySensorEntity):
    """A single OPCOM automation binary sensor."""

    entity_description: OpcomBinarySensorDescription

    def __init__(
        self,
        coordinator: OpcomCoordinator,
        entry: ConfigEntry,
        res: str,
        description: OpcomBinarySensorDescription,
    ) -> None:
        self.entity_description = description
        super().__init__(coordinator, entry, res)

    @property
    def _config(self) -> OpcomConfig:
        return self.coordinator.config

    @property
    def _res_minutes(self) -> int:
        return RESOLUTIONS[self._res]

    def _agg_today(self):
        return aggregate(self.coordinator.get_day("today"), self._res_minutes)

    @property
    def available(self) -> bool:
        if not self.coordinator.last_update_success:
            return False
        day = self.coordinator.get_day("today")
        return day is not None and day.has_data

    @property
    def is_on(self) -> bool | None:
        kind = self.entity_description.kind
        cfg = self._config
        agg = self._agg_today()
        cur, _ = current_and_next(agg)
        if not cur:
            return None
        cur_price = cur.price

        if kind == "should_charge_now":
            windows = compute_windows(
                agg, cfg.window_minutes, cfg.num_windows, "cheap"
            )
            if not in_any_window(cur, windows):
                return False
            if cfg.low_threshold is not None and cur_price > cfg.low_threshold:
                return False
            return True

        if kind == "should_discharge_now":
            windows = compute_windows(
                agg, cfg.window_minutes, cfg.num_windows, "expensive"
            )
            if not in_any_window(cur, windows):
                return False
            if cfg.high_threshold is not None and cur_price < cfg.high_threshold:
                return False
            return True

        if kind == "price_below_threshold":
            if cfg.low_threshold is None:
                return None
            return cur_price < cfg.low_threshold

        if kind == "price_above_threshold":
            if cfg.high_threshold is None:
                return None
            return cur_price > cfg.high_threshold

        if kind == "cheap_percentile_now":
            rank = percentile_rank(cur_price, [a.price for a in agg])
            return rank is not None and rank <= cfg.percentile_low

        if kind == "expensive_percentile_now":
            rank = percentile_rank(cur_price, [a.price for a in agg])
            return rank is not None and rank >= cfg.percentile_high

        return None

    @property
    def extra_state_attributes(self):
        kind = self.entity_description.kind
        cfg = self._config
        agg = self._agg_today()
        cur, _ = current_and_next(agg)
        if not cur:
            return None
        attrs = {
            "current_price": round(cur.price, 2),
            "interval_index": cur.index,
            "resolution": self._res,
        }
        if kind in ("should_charge_now", "should_discharge_now"):
            mode = "cheap" if kind == "should_charge_now" else "expensive"
            windows = compute_windows(agg, cfg.window_minutes, cfg.num_windows, mode)
            attrs["window_minutes"] = cfg.window_minutes
            attrs["num_windows"] = cfg.num_windows
            attrs["in_window"] = in_any_window(cur, windows)
            if cfg.low_threshold is not None and kind == "should_charge_now":
                attrs["threshold"] = cfg.low_threshold
            if cfg.high_threshold is not None and kind == "should_discharge_now":
                attrs["threshold"] = cfg.high_threshold
        elif kind in ("price_below_threshold", "price_above_threshold"):
            attrs["threshold"] = cfg.low_threshold if kind == "price_below_threshold" else cfg.high_threshold
        elif kind in ("cheap_percentile_now", "expensive_percentile_now"):
            attrs["percentile_low"] = cfg.percentile_low
            attrs["percentile_high"] = cfg.percentile_high
        return attrs

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up OPCOM binary sensors for each configured resolution."""
    coordinator: OpcomCoordinator = hass.data[DOMAIN][entry.entry_id]
    config: OpcomConfig = coordinator.config

    entities: list[OpcomBinarySensor] = []
    for res in sorted(config.resolutions, key=lambda r: RESOLUTIONS[r]):
        for description in BASE_BINARY:
            entities.append(OpcomBinarySensor(coordinator, entry, res, description))
        if config.low_threshold is not None:
            entities.append(OpcomBinarySensor(coordinator, entry, res, LOW_THRESHOLD_BINARY))
        if config.high_threshold is not None:
            entities.append(OpcomBinarySensor(coordinator, entry, res, HIGH_THRESHOLD_BINARY))

    async_add_entities(entities)