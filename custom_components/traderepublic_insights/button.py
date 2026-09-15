"""Button to refresh data and force a timeline sync."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TRConfigEntry
from .entity import TREntity


async def async_setup_entry(hass: HomeAssistant, entry: TRConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    async_add_entities([TRRefreshButton(entry.runtime_data)])


class TRRefreshButton(TREntity, ButtonEntity):
    _attr_translation_key = "refresh"
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "refresh")
        self.entity_id = "button.trade_republic_refresh"

    async def async_press(self) -> None:
        self.coordinator.sync.force_timeline = True
        await self.coordinator.async_request_refresh()
