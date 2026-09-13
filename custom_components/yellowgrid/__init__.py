"""The YellowGrid Romania prices integration.

Sets up a single :class:`YellowGridCoordinator` per config entry and forwards
setup to the ``sensor`` and ``button`` platforms.

The rotating ``userToken`` session cookie is persisted in a HA ``Store`` (not
in ``entry.data``) so that the coordinator can update it on every poll without
triggering a config-entry reload. ``entry.data`` keeps the user's initial paste
as a fallback for the very first run after setup or reauth.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import CONF_USER_TOKEN, DOMAIN, PLATFORMS, STORAGE_VERSION, YellowGridConfig
from .coordinator import YellowGridCoordinator

_LOGGER = logging.getLogger(__name__)

type YellowGridEntry = ConfigEntry  # convenience alias


def _token_store(hass: HomeAssistant, entry_id: str) -> Store:
    """The persistent store for the rotating session token."""
    return Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}.token")


async def async_load_token(hass: HomeAssistant, entry: ConfigEntry) -> str | None:
    """Return the latest persisted token, or None if never stored."""
    data: dict[str, Any] | None = await _token_store(hass, entry.entry_id).async_load()
    if not data:
        return None
    return data.get(CONF_USER_TOKEN)


async def async_save_token(hass: HomeAssistant, entry: ConfigEntry, token: str) -> None:
    """Persist the current (possibly renewed) token."""
    await _token_store(hass, entry.entry_id).async_save({CONF_USER_TOKEN: token})


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """YAML setup is not supported; everything goes through the UI flow."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up YellowGrid from a config entry."""
    config = YellowGridConfig.from_entry(entry.data)

    # Prefer the persisted (rotated) token; fall back to the initial paste.
    current_token = await async_load_token(hass, entry)
    if not current_token:
        current_token = config.user_token
        await async_save_token(hass, entry, current_token)

    coordinator = YellowGridCoordinator(hass, entry, config, current_token)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _LOGGER.info(
        "YellowGrid integration initialised (device=%s, refresh=%d min)",
        config.device_id,
        config.refresh_interval,
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok