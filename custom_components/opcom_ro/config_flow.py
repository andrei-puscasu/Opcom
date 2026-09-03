"""Config flow and options flow for the OPCOM Romania integration.

A single page collects currency, resolutions, polling cadence and the
optimal-window / threshold parameters used by the battery-automation sensors.
The same schema powers both the initial setup and the options dialog, so
changing any setting later reuses exactly the same controls.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_CURRENCY,
    CONF_HIGH_THRESHOLD,
    CONF_LOW_THRESHOLD,
    CONF_NUM_WINDOWS,
    CONF_PERCENTILE_HIGH,
    CONF_PERCENTILE_LOW,
    CONF_REFRESH_INTERVAL,
    CONF_RESOLUTIONS,
    CONF_WINDOW_MINUTES,
    CONF_ENABLE_DEBUG_LOG,
    CURRENCY_EUR,
    CURRENCY_RON,
    DEFAULT_CURRENCY,
    DEFAULT_NUM_WINDOWS,
    DEFAULT_PERCENTILE_HIGH,
    DEFAULT_PERCENTILE_LOW,
    DEFAULT_REFRESH_INTERVAL,
    DEFAULT_RESOLUTIONS,
    DEFAULT_WINDOW_MINUTES,
    DOMAIN,
    RESOLUTIONS,
)


_RESOLUTION_OPTIONS = [
    {"value": res, "label": f"{RESOLUTIONS[res]} min"}
    for res in ("PT15M", "PT30M", "PT60M")
]

_CURRENCY_OPTIONS = [
    {"value": CURRENCY_RON, "label": "RON (lei/MWh)"},
    {"value": CURRENCY_EUR, "label": "EUR (EUR/MWh)"},
]


def _num(min_val, max_val, unit, step=1):
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=min_val,
            max=max_val,
            step=step,
            unit_of_measurement=unit,
            mode=selector.NumberSelectorMode.SLIDER,
        )
    )


def _threshold_default(user_input: dict[str, Any], key: str) -> float:
    """Slider default for an optional price threshold.

    The value is stored as ``None`` when disabled, but a NumberSelector always
    runs ``vol.Coerce(float)`` on its default — and ``float(None)`` raises
    "expected float". Show a numeric 0 instead; 0 is treated as "disabled"
    everywhere else (see OpcomConfig.from_entry), so the semantics are
    preserved.
    """
    val = user_input.get(key)
    if val in (None, "", 0):
        return 0
    return val


def build_schema(user_input: dict[str, Any] | None = None) -> vol.Schema:
    """Build the config/options schema, pre-filled from existing entry data."""
    user_input = user_input or {}

    def get(key, default):
        return user_input.get(key, default)

    return vol.Schema(
        {
            vol.Required(
                CONF_CURRENCY, default=get(CONF_CURRENCY, DEFAULT_CURRENCY)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_CURRENCY_OPTIONS,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_RESOLUTIONS, default=get(CONF_RESOLUTIONS, list(DEFAULT_RESOLUTIONS))
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_RESOLUTION_OPTIONS,
                    multiple=True,
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
            vol.Required(
                CONF_REFRESH_INTERVAL,
                default=get(CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL),
            ): _num(1, 60, "min"),
            vol.Required(
                CONF_WINDOW_MINUTES, default=get(CONF_WINDOW_MINUTES, DEFAULT_WINDOW_MINUTES)
            ): _num(15, 480, "min", step=15),
            vol.Required(
                CONF_NUM_WINDOWS, default=get(CONF_NUM_WINDOWS, DEFAULT_NUM_WINDOWS)
            ): _num(1, 24, "ferestre"),
            vol.Optional(
                CONF_LOW_THRESHOLD, default=_threshold_default(user_input, CONF_LOW_THRESHOLD)
            ): _num(0, 10000, "lei/MWh"),
            vol.Optional(
                CONF_HIGH_THRESHOLD, default=_threshold_default(user_input, CONF_HIGH_THRESHOLD)
            ): _num(0, 10000, "lei/MWh"),
            vol.Required(
                CONF_PERCENTILE_LOW, default=get(CONF_PERCENTILE_LOW, DEFAULT_PERCENTILE_LOW)
            ): _num(1, 99, "%"),
            vol.Required(
                CONF_PERCENTILE_HIGH, default=get(CONF_PERCENTILE_HIGH, DEFAULT_PERCENTILE_HIGH)
            ): _num(1, 99, "%"),
            vol.Optional(
                CONF_ENABLE_DEBUG_LOG, default=get(CONF_ENABLE_DEBUG_LOG, False)
            ): selector.BooleanSelector(),
        }
    )


class OpcomConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial setup of the OPCOM integration."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            # 0 / "" / None all mean "threshold disabled" (see OpcomConfig.from_entry).
            if not user_input.get(CONF_LOW_THRESHOLD):
                user_input[CONF_LOW_THRESHOLD] = None
            if not user_input.get(CONF_HIGH_THRESHOLD):
                user_input[CONF_HIGH_THRESHOLD] = None
            if not user_input.get(CONF_RESOLUTIONS):
                return self.async_show_form(
                    step_id="user",
                    data_schema=build_schema(user_input),
                    errors={"base": "no_resolutions"},
                )
            return self.async_create_entry(
                title="OPCOM Romania", data=user_input
            )

        return self.async_show_form(
            step_id="user", data_schema=build_schema(), last_step=True
        )

    async def async_step_import(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Support YAML import (best-effort)."""
        return await self.async_step_user(user_input)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OpcomOptionsFlowHandler:
        return OpcomOptionsFlowHandler(config_entry)


class OpcomOptionsFlowHandler(config_entries.OptionsFlow):
    """Options flow: reuses the same schema as initial setup."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            if not user_input.get(CONF_LOW_THRESHOLD):
                user_input[CONF_LOW_THRESHOLD] = None
            if not user_input.get(CONF_HIGH_THRESHOLD):
                user_input[CONF_HIGH_THRESHOLD] = None
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=build_schema(self.config_entry.data),
        )