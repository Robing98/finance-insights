"""Button to refresh data and force a sync with the provider."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import FIConfigEntry
from .entity import FIEntity


async def async_setup_entry(hass: HomeAssistant, entry: FIConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    async_add_entities([FIRefreshButton(entry.runtime_data)])


class FIRefreshButton(FIEntity, ButtonEntity):
    _attr_translation_key = "refresh"
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "refresh", "button")

    async def async_press(self) -> None:
        self.coordinator.sync.force = True
        await self.coordinator.async_request_refresh()
