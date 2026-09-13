"""Config flow, reauth flow and options flow for the YellowGrid integration.

The initial setup collects two values the user copies from the YellowGrid
portal (see the install guide for how to extract them):

* ``user_token``  - the ``userToken`` cookie value (a long URL-encoded blob).
* ``device_id``   - the plant UUID.

A test fetch validates the token before the entry is created. When the token
later expires (HTTP 401), HA's reauth machinery opens ``async_step_reauth``,
which lets the user paste a fresh cookie without re-entering the device id.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_DEVICE_ID,
    CONF_REFRESH_INTERVAL,
    CONF_USER_TOKEN,
    DEFAULT_REFRESH_INTERVAL,
    DOMAIN,
    MARKET_TZ,
)
from .api import YellowGridApiError, YellowGridAuthError, async_fetch_earnings


def _today_market() -> date:
    from datetime import datetime

    return datetime.now(MARKET_TZ).date()


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


def _user_schema(user_input: dict[str, Any] | None = None) -> vol.Schema:
    user_input = user_input or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_USER_TOKEN, default=user_input.get(CONF_USER_TOKEN, "")
            ): selector.TextSelector(
                selector.TextSelectorConfig(
                    multiline=True,
                    type=selector.TextSelectorType.TEXT,
                )
            ),
            vol.Required(
                CONF_DEVICE_ID, default=user_input.get(CONF_DEVICE_ID, "")
            ): selector.TextSelector(
                selector.TextSelectorConfig(
                    multiline=False, type=selector.TextSelectorType.TEXT
                )
            ),
            vol.Required(
                CONF_REFRESH_INTERVAL,
                default=user_input.get(CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL),
            ): _num(5, 120, "min"),
        }
    )


def _reauth_schema(user_input: dict[str, Any] | None = None) -> vol.Schema:
    user_input = user_input or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_USER_TOKEN, default=user_input.get(CONF_USER_TOKEN, "")
            ): selector.TextSelector(
                selector.TextSelectorConfig(
                    multiline=True,
                    type=selector.TextSelectorType.TEXT,
                )
            )
        }
    )


def _options_schema(user_input: dict[str, Any] | None = None) -> vol.Schema:
    user_input = user_input or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_DEVICE_ID, default=user_input.get(CONF_DEVICE_ID, "")
            ): selector.TextSelector(
                selector.TextSelectorConfig(
                    multiline=False, type=selector.TextSelectorType.TEXT
                )
            ),
            vol.Required(
                CONF_REFRESH_INTERVAL,
                default=user_input.get(CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL),
            ): _num(5, 120, "min"),
        }
    )


async def _validate_token(
    hass, user_token: str, device_id: str
) -> str | None:
    """Run a live earnings fetch to verify the token+device.

    Returns a translation error key (``invalid_token`` / ``cannot_connect``) on
    failure, or ``None`` on success.
    """
    try:
        await async_fetch_earnings(user_token, device_id, _today_market())
    except YellowGridAuthError:
        return "invalid_token"
    except YellowGridApiError:
        return "cannot_connect"
    except Exception:  # noqa: BLE001 - any unexpected transport issue
        return "cannot_connect"
    return None


class YellowGridConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial setup of the YellowGrid integration."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            token = (user_input.get(CONF_USER_TOKEN) or "").strip()
            device = (user_input.get(CONF_DEVICE_ID) or "").strip()
            if not token or not device:
                errors["base"] = "missing_fields"
            else:
                # Guard against duplicate entries for the same plant.
                await self.async_set_unique_id(f"{DOMAIN}-{device}")
                self._abort_if_unique_id_configured()
                error = await _validate_token(self.hass, token, device)
                if error:
                    errors["base"] = error
                else:
                    return self.async_create_entry(
                        title=f"YellowGrid {device[:8]}",
                        data={
                            CONF_USER_TOKEN: token,
                            CONF_DEVICE_ID: device,
                            CONF_REFRESH_INTERVAL: int(
                                user_input.get(
                                    CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL
                                )
                            ),
                        },
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(user_input),
            errors=errors,
            last_step=True,
        )

    async def async_step_import(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Support YAML import (best-effort)."""
        return await self.async_step_user(user_input)

    async def async_step_reauth(
        self, entry_data: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Start the reauth flow when the token expires."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Let the user paste a fresh ``userToken`` cookie."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            token = (user_input.get(CONF_USER_TOKEN) or "").strip()
            if not token:
                errors["base"] = "missing_fields"
            else:
                error = await _validate_token(
                    self.hass, token, entry.data.get(CONF_DEVICE_ID, "")
                )
                if error:
                    errors["base"] = error
                else:
                    # Persist the new token immediately so the reload picks it
                    # up, then update entry.data as the fallback.
                    from . import async_save_token

                    await async_save_token(self.hass, entry, token)
                    self.hass.config_entries.async_update_entry(
                        entry,
                        data={**entry.data, CONF_USER_TOKEN: token},
                    )
                    await self.hass.config_entries.async_reload(entry.entry_id)
                    return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_reauth_schema(),
            description_placeholders={"device_id": entry.data.get(CONF_DEVICE_ID, "")},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "YellowGridOptionsFlowHandler":
        return YellowGridOptionsFlowHandler(config_entry)


class YellowGridOptionsFlowHandler(config_entries.OptionsFlow):
    """Options flow: edit the device id and refresh interval."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(self.config_entry.data),
        )