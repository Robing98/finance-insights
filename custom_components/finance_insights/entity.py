"""Base entity."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import FIBaseCoordinator


class FIEntity(CoordinatorEntity[FIBaseCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: FIBaseCoordinator, key: str, platform: str = "sensor") -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        # Stable English entity IDs so the example dashboards work in every UI language.
        self.entity_id = f"{platform}.{coordinator.entity_prefix}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=coordinator.device_name,
            manufacturer="Finance Insights (unofficial)",
            entry_type=DeviceEntryType.SERVICE,
        )
