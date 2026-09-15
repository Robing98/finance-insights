"""Sensors for all account types."""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import FIConfigEntry
from .const import TYPE_BANK, TYPE_OVERVIEW, TYPE_TRADE_REPUBLIC
from .coordinator import FIBaseCoordinator
from .descriptions import EUR, FISensorDescription
from .entity import FIEntity
from .sensors_bank import BANK_SENSORS
from .sensors_overview import OVERVIEW_SENSORS
from .sensors_tr import ASSET_ICONS, SUMMARY

DESCRIPTIONS = {TYPE_TRADE_REPUBLIC: SUMMARY, TYPE_BANK: BANK_SENSORS, TYPE_OVERVIEW: OVERVIEW_SENSORS}
LARGE_ATTRIBUTES = frozenset({
    "last_12_months", "by_category", "by_kind", "allocation", "bonds", "doubtful", "monthly", "groups_12m", "total_12m",
    "avg_month_12m", "categories_12m", "merchants_12m", "merchants_month", "by_year", "history", "recurring", "accounts",
    "split", "kinds_12m", "warnings",
})


async def async_setup_entry(hass: HomeAssistant, entry: FIConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [FISensor(coordinator, d) for d in DESCRIPTIONS[coordinator.kind]]
    if coordinator.kind != TYPE_OVERVIEW:
        entities.append(FIStatusSensor(coordinator))
    async_add_entities(entities)
    if coordinator.kind != TYPE_TRADE_REPUBLIC:
        return

    known: set[str] = set()

    @callback
    def _add_new_holdings() -> None:
        new = [h for h in coordinator.data["holdings"] if h["symbol"] not in known]
        if new:
            known.update(h["symbol"] for h in new)
            async_add_entities([HoldingSensor(coordinator, h["symbol"], h["name"], h["asset_class"]) for h in new])

    _add_new_holdings()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_holdings))


class FISensor(FIEntity, SensorEntity):
    entity_description: FISensorDescription
    _unrecorded_attributes = LARGE_ATTRIBUTES

    def __init__(self, coordinator: FIBaseCoordinator, description: FISensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self):
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self):
        fn = self.entity_description.attrs_fn
        return fn(self.coordinator.data) if fn else None


class FIStatusSensor(FIEntity, SensorEntity):
    _attr_translation_key = "data_status"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:database-sync"
    _unrecorded_attributes = LARGE_ATTRIBUTES

    def __init__(self, coordinator: FIBaseCoordinator) -> None:
        super().__init__(coordinator, "data_status")

    @property
    def native_value(self):
        return self.coordinator.sync.status

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data
        return {**data.get("meta", {}), "last_sync": self.coordinator.sync.last_sync,
                "warnings": data.get("warnings", [])[:25]}


class HoldingSensor(FIEntity, SensorEntity):
    _attr_native_unit_of_measurement = EUR
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator: FIBaseCoordinator, symbol: str, name: str, asset_class: str) -> None:
        super().__init__(coordinator, f"holding_{symbol}")
        # Holding entity IDs come from the device and holding name, as before.
        self.entity_id = None
        self._symbol = symbol
        self._attr_name = name
        self._attr_icon = ASSET_ICONS.get(asset_class, "mdi:briefcase-outline")

    def _holding(self):
        return next((h for h in self.coordinator.data["holdings"] if h["symbol"] == self._symbol), None)

    @property
    def available(self) -> bool:
        return super().available and self._holding() is not None

    @property
    def native_value(self):
        h = self._holding()
        return h["value"] if h else None

    @property
    def extra_state_attributes(self):
        h = self._holding()
        if not h:
            return None
        keys = ("symbol", "asset_class", "shares", "avg_cost", "price", "price_unit", "price_source",
                "cost", "unrealized", "unrealized_pct", "weight_pct", "dividends", "dividends_12m", "dividends_tax",
                "last_dividend", "return_incl_dividends", "return_incl_dividends_pct")
        return {"trade_republic_holding": True, **{k: h[k] for k in keys}}
