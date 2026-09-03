"""Button platform: troubleshooting helpers exposed as buttons.

* ``clear_debug_log`` - empties the ``opcom_ro_debug.log`` file so the user
  can reproduce an issue from a clean state before sharing the log.
* ``refresh_now``    - triggers an immediate OPCOM refresh (useful while
  debugging, instead of waiting for the next poll).

These belong to an entry-level device (``OPCOM Romania``), separate from the
per-resolution price devices.
"""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import OpcomCoordinator


@dataclass
class OpcomButtonDescription(ButtonEntityDescription):
    kind: str = ""


BUTTONS: tuple[OpcomButtonDescription, ...] = (
    OpcomButtonDescription(
        key="clear_debug_log",
        translation_key="clear_debug_log",
        kind="clear_debug_log",
        icon="mdi:file-document-outline",
    ),
    OpcomButtonDescription(
        key="refresh_now",
        translation_key="refresh_now",
        kind="refresh_now",
        icon="mdi:refresh",
    ),
)


class OpcomButton(CoordinatorEntity[OpcomCoordinator], ButtonEntity):
    """A button that performs a one-shot troubleshooting action."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: OpcomCoordinator,
        entry: ConfigEntry,
        description: OpcomButtonDescription,
    ) -> None:
        self.entity_description = description
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "OPCOM Romania",
            "manufacturer": "OPCOM",
            "model": "Day-Ahead Market (PZU)",
        }

    async def async_press(self) -> None:
        kind = self.entity_description.kind
        if kind == "clear_debug_log":
            self.coordinator.file_log.clear()
        elif kind == "refresh_now":
            self.coordinator.file_log.log("info", "Manual refresh requested")
            await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up OPCOM troubleshooting buttons."""
    coordinator: OpcomCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([OpcomButton(coordinator, entry, d) for d in BUTTONS])