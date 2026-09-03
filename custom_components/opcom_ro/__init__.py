"""The OPCOM Romania day-ahead prices integration.

Sets up a single :class:`OpcomCoordinator` per config entry and forwards setup
to the ``sensor`` and ``binary_sensor`` platforms. Options changes trigger a
full reload of the entry so entity creation (which depends on the selected
resolutions and thresholds) stays consistent.
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PLATFORMS, OpcomConfig
from .coordinator import OpcomCoordinator

_LOGGER = logging.getLogger(__name__)

type OpcomEntry = ConfigEntry  # convenience alias


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up via YAML is not supported; everything goes through the UI flow."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up OPCOM from a config entry."""
    config = OpcomConfig.from_entry(entry.data)
    coordinator = OpcomCoordinator(hass, config)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    _LOGGER.info("OPCOM Romania integration initialised (%s)", config.currency)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok


async def _async_update_listener(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)