"""Button platform: a manual refresh action.

* ``refresh_now`` - triggers an immediate earnings fetch instead of waiting for
  the next poll. Useful while debugging or after re-pasting a token.
"""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import YellowGridCoordinator


@dataclass
class YellowGridButtonDescription(ButtonEntityDescription):
    kind: str = ""


BUTTONS: tuple[YellowGridButtonDescription, ...] = (
    YellowGridButtonDescription(
        key="refresh_now",
        translation_key="refresh_now",
        kind="refresh_now",
        icon="mdi:refresh",
    ),
)


class YellowGridButton(CoordinatorEntity[YellowGridCoordinator], ButtonEntity):
    """A button that performs a one-shot action."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: YellowGridCoordinator,
        entry: ConfigEntry,
        description: YellowGridButtonDescription,
    ) -> None:
        self.entity_description = description
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "YellowGrid",
            "manufacturer": "YELLOWGRID PROD SRL",
            "model": "Prosumer plant",
        }

    async def async_press(self) -> None:
        if self.entity_description.kind == "refresh_now":
            await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up YellowGrid buttons."""
    coordinator: YellowGridCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [YellowGridButton(coordinator, entry, d) for d in BUTTONS]
    )