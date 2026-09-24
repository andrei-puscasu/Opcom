"""Sensor platform for YellowGrid prosumer prices.

YellowGrid bills a prosumer per 15-minute interval with two prices:

* **Import** (``importPrice``) - what you pay to consume from the grid. This is
  a flat retail tariff (~1.31 lei/kWh), essentially independent of the
  wholesale market.
* **Export** (``exportPrice``) - what you earn for injecting surplus PV. This
  varies through the day and is the price that matters for export/battery
  optimisation.

Sensors exposed:

* ``current_import_price`` / ``current_export_price`` - the price of the
  15-min slot in progress, with the full 96-interval day curve as attributes
  (``import_prices`` / ``export_prices``) so it can be plotted directly.
* ``current_interval`` - the 1..96 index of the slot in progress.
* ``today_import_energy`` / ``today_export_energy`` - daily totals in kWh.
* ``today_earnings`` / ``today_savings`` - daily totals in RON (lei).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MARKET_TZ
from .coordinator import YellowGridCoordinator
from .models import YGEarnings, YGInterval

_PRICE_UNIT = "lei/kWh"
# Currency code for the MONETARY device class. Defined locally because the
# ``CURRENCY_RON`` constant was removed from ``homeassistant.const`` in recent
# Home Assistant versions; the raw ISO 4217 string is accepted directly.
_CURRENCY_RON = "RON"


@dataclass
class YGSensorDescription(SensorEntityDescription):
    """Sensor entity description with a behaviour ``kind``."""

    kind: str = ""


SENSORS: tuple[YGSensorDescription, ...] = (
    YGSensorDescription(
        key="current_import_price",
        translation_key="current_import_price",
        kind="current_import_price",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:transmission-tower-import",
        suggested_display_precision=3,
    ),
    YGSensorDescription(
        key="current_export_price",
        translation_key="current_export_price",
        kind="current_export_price",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:transmission-tower-export",
        suggested_display_precision=3,
    ),
    YGSensorDescription(
        key="current_interval",
        translation_key="current_interval",
        kind="current_interval",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:clock-time-four-outline",
    ),
    YGSensorDescription(
        key="today_import_energy",
        translation_key="today_import_energy",
        kind="today_import_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        icon="mdi:flash",
        suggested_display_precision=2,
    ),
    YGSensorDescription(
        key="today_export_energy",
        translation_key="today_export_energy",
        kind="today_export_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        icon="mdi:solar-power",
        suggested_display_precision=2,
    ),
    YGSensorDescription(
        key="today_earnings",
        translation_key="today_earnings",
        kind="today_earnings",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=_CURRENCY_RON,
        icon="mdi:cash-check",
        suggested_display_precision=2,
    ),
    YGSensorDescription(
        key="today_savings",
        translation_key="today_savings",
        kind="today_savings",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=_CURRENCY_RON,
        icon="mdi:piggy-bank",
        suggested_display_precision=2,
    ),
    YGSensorDescription(
        key="today_export_price_max",
        translation_key="today_export_price_max",
        kind="today_export_price_max",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:arrow-up-bold",
        suggested_display_precision=4,
    ),
    YGSensorDescription(
        key="today_export_price_min",
        translation_key="today_export_price_min",
        kind="today_export_price_min",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:arrow-down-bold",
        suggested_display_precision=4,
    ),
)


def _interval_bounds(index: int, delivery_day) -> tuple[datetime, datetime]:
    """Start/end (market-local) datetimes for a 1-based interval index."""
    midnight = datetime.combine(delivery_day, datetime.min.time(), tzinfo=MARKET_TZ)
    start = midnight + (index - 1) * timedelta(minutes=15)
    return start, start + timedelta(minutes=15)


def _price_curves(earnings: YGEarnings) -> tuple[dict[str, float], dict[str, float]]:
    """Build {HH:MM: price} curves for import and export across all intervals."""
    import_prices: dict[str, float] = {}
    export_prices: dict[str, float] = {}
    for iv in earnings.intervals:
        start, _ = _interval_bounds(iv.index, earnings.delivery_day)
        key = start.strftime("%H:%M")
        import_prices[key] = round(iv.import_price, 4)
        export_prices[key] = round(iv.export_price, 4)
    return import_prices, export_prices


class YellowGridEntity(CoordinatorEntity[YellowGridCoordinator]):
    """Common base: device grouping and unique id."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: YellowGridCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "YellowGrid",
            "manufacturer": "YELLOWGRID PROD SRL",
            "model": "Prosumer plant",
        }


class YellowGridSensor(YellowGridEntity, SensorEntity):
    """A single YellowGrid price/energy/earnings sensor."""

    entity_description: YGSensorDescription

    def __init__(
        self,
        coordinator: YellowGridCoordinator,
        entry: ConfigEntry,
        description: YGSensorDescription,
    ) -> None:
        self.entity_description = description
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        # Price sensors use lei/kWh; the rest set their unit via the description.
        if description.kind in (
            "current_import_price",
            "current_export_price",
            "today_export_price_max",
            "today_export_price_min",
        ):
            self._attr_native_unit_of_measurement = _PRICE_UNIT

    # -- helpers ------------------------------------------------------------

    @property
    def _earnings(self) -> YGEarnings | None:
        return self.coordinator.get_earnings()

    @property
    def _current(self) -> YGInterval | None:
        earnings = self._earnings
        if not earnings:
            return None
        return earnings.interval(self.coordinator.current_interval_index())

    # -- availability -------------------------------------------------------

    @property
    def available(self) -> bool:
        earnings = self._earnings
        # Guard against stale cross-day cache: between midnight and the first
        # successful poll of the new day (and during transient failures that
        # keep the last good data), ``_last_earnings`` still belongs to
        # yesterday. HA's DataUpdateCoordinator leaves ``last_update_success``
        # True on UpdateFailed, so without this guard the "today" sensors would
        # display yesterday's totals under today's labels.
        return (
            self.coordinator.last_update_success
            and earnings is not None
            and earnings.has_data
            and earnings.delivery_day == self.coordinator.today_date
        )

    # -- value / attributes -------------------------------------------------

    @property
    def native_value(self) -> float | int | None:
        kind = self.entity_description.kind
        earnings = self._earnings
        if earnings is None or not earnings.has_data:
            return None

        if kind == "current_import_price":
            cur = self._current
            return cur.import_price if cur else None
        if kind == "current_export_price":
            cur = self._current
            return cur.export_price if cur else None
        if kind == "current_interval":
            return self.coordinator.current_interval_index()
        if kind == "today_import_energy":
            return round(earnings.total_import, 3)
        if kind == "today_export_energy":
            return round(earnings.total_export, 3)
        if kind == "today_earnings":
            return round(earnings.total_earnings, 2)
        if kind == "today_savings":
            return round(earnings.total_savings, 2)
        if kind in ("today_export_price_max", "today_export_price_min"):
            prices = [iv.export_price for iv in earnings.intervals]
            if not prices:
                return None
            extreme = max(prices) if kind == "today_export_price_max" else min(prices)
            return round(extreme, 4)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        kind = self.entity_description.kind
        earnings = self._earnings
        if earnings is None or not earnings.has_data:
            return None

        if kind in ("current_import_price", "current_export_price"):
            cur = self._current
            if not cur:
                return None
            start, end = _interval_bounds(cur.index, earnings.delivery_day)
            import_prices, export_prices = _price_curves(earnings)
            return {
                "interval_index": cur.index,
                "interval_start": start.isoformat(),
                "interval_end": end.isoformat(),
                "delivery_day": earnings.delivery_day.isoformat(),
                "device_id": earnings.device_id,
                "current_import_price": round(cur.import_price, 4),
                "current_export_price": round(cur.export_price, 4),
                "import_prices": import_prices,
                "export_prices": export_prices,
                "total_import_kwh": round(earnings.total_import, 3),
                "total_export_kwh": round(earnings.total_export, 3),
                "total_earnings_ron": round(earnings.total_earnings, 2),
            }

        if kind == "current_interval":
            idx = self.coordinator.current_interval_index()
            start, end = _interval_bounds(idx, earnings.delivery_day)
            return {
                "interval_start": start.isoformat(),
                "interval_end": end.isoformat(),
                "delivery_day": earnings.delivery_day.isoformat(),
            }

        if kind in ("today_import_energy", "today_export_energy",
                    "today_earnings", "today_savings"):
            return {
                "delivery_day": earnings.delivery_day.isoformat(),
                "device_id": earnings.device_id,
                "intervals": len(earnings.intervals),
            }

        if kind in ("today_export_price_max", "today_export_price_min"):
            priced = [
                (iv.export_price, iv.index) for iv in earnings.intervals
            ]
            if not priced:
                return None
            if kind == "today_export_price_max":
                val, idx = max(priced, key=lambda t: t[0])
            else:
                val, idx = min(priced, key=lambda t: t[0])
            start, _ = _interval_bounds(idx, earnings.delivery_day)
            return {
                "extreme_at": start.strftime("%H:%M"),
                "extreme_interval_index": idx,
                "extreme_price": round(val, 4),
                "delivery_day": earnings.delivery_day.isoformat(),
                "intervals": len(earnings.intervals),
            }

        return None

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up YellowGrid sensors."""
    coordinator: YellowGridCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [YellowGridSensor(coordinator, entry, d) for d in SENSORS]
    )