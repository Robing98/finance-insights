"""Finance Insights: brokerage and bank accounts as Home Assistant sensors."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType
from homeassistant.requirements import RequirementsNotFound, async_process_requirements

from .const import (
    ATTR_DASHBOARD, CONF_USE_FINTS, CONF_USE_PYTR, DASHBOARD_STORE_KEY, DOMAIN, FINTS_REQUIREMENT, PYTR_REQUIREMENT,
    SERVICE_BUILD_DASHBOARD,
)
from .coordinator import COORDINATORS, FIBaseCoordinator, FinanceHub, account_type

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR, Platform.BUTTON]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
DATA_DASHBOARD = f"{DOMAIN}_dashboard"

type FIConfigEntry = ConfigEntry[FIBaseCoordinator]


class DashboardManager:
    """Remembers the dashboard chosen with the build_dashboard action and rebuilds it when accounts change."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.store: Store[dict] = Store(hass, 1, DASHBOARD_STORE_KEY)
        self.url_path: str | None = None
        self.debouncer = Debouncer(hass, _LOGGER, cooldown=5, immediate=False, function=self._rebuild)

    async def async_load(self) -> None:
        self.url_path = ((await self.store.async_load()) or {}).get(ATTR_DASHBOARD)

    async def async_build(self, url_path: str) -> int:
        from .dashboard import async_build_dashboard

        count = await async_build_dashboard(self.hass, url_path)
        self.url_path = url_path
        await self.store.async_save({ATTR_DASHBOARD: url_path})
        return count

    async def _rebuild(self) -> None:
        if not self.url_path:
            return
        from .dashboard import async_build_dashboard

        try:
            await async_build_dashboard(self.hass, self.url_path)
        except Exception as err:  # noqa: BLE001 - a missing dashboard must not break the integration
            _LOGGER.warning("Could not rebuild dashboard %s: %s", self.url_path, err)

    @callback
    def schedule(self) -> None:
        if self.url_path:
            self.hass.async_create_task(self.debouncer.async_call())


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    manager = DashboardManager(hass)
    await manager.async_load()
    hass.data[DATA_DASHBOARD] = manager

    async def build(call: ServiceCall) -> ServiceResponse:
        return {"views": await manager.async_build(call.data[ATTR_DASHBOARD])}

    hass.services.async_register(DOMAIN, SERVICE_BUILD_DASHBOARD, build,
                                 schema=vol.Schema({vol.Required(ATTR_DASHBOARD): cv.string}),
                                 supports_response=SupportsResponse.OPTIONAL)
    return True


def _hub(hass: HomeAssistant) -> FinanceHub:
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = FinanceHub(hass)
    return hass.data[DOMAIN]


async def async_setup_entry(hass: HomeAssistant, entry: FIConfigEntry) -> bool:
    requirements = []
    if entry.data.get(CONF_USE_PYTR):
        requirements.append(PYTR_REQUIREMENT)
    if entry.data.get(CONF_USE_FINTS):
        requirements.append(FINTS_REQUIREMENT)
    if requirements:
        try:
            await async_process_requirements(hass, DOMAIN, requirements)
        except RequirementsNotFound as err:
            raise ConfigEntryNotReady(f"Could not install {', '.join(requirements)}") from err

    hub = _hub(hass)
    coordinator = COORDINATORS[account_type(entry)](hass, entry, hub)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    hub.register(coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_reload_on_options))
    # Other accounts may already be loaded: match transfers and refresh the overview.
    hub._recompute(coordinator.kind, coordinator)  # noqa: SLF001
    hass.data[DATA_DASHBOARD].schedule()
    return True


async def _reload_on_options(hass: HomeAssistant, entry: FIConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: FIConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok and DOMAIN in hass.data:
        hass.data[DOMAIN].unregister(entry.entry_id)
        hass.data[DATA_DASHBOARD].schedule()
    return ok
