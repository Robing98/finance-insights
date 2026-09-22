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
from homeassistant.util import dt as dt_util

from . import demo
from .const import (
    CONF_DEMO,
    ATTR_DASHBOARD, ATTR_LANGUAGE, ATTR_RESET, ATTR_THEME, CONF_USE_FINTS, CONF_USE_PYTR, DASHBOARD_STORE_KEY, DOMAIN, FINTS_REQUIREMENT, PYTR_REQUIREMENT,
    SERVICE_BACKFILL_HISTORY, SERVICE_BUILD_DASHBOARD, THEME_NAME,
)
from .coordinator import COORDINATORS, FIBaseCoordinator, FinanceHub, account_type
from .ui import async_install_theme, async_register_frontend

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR, Platform.BUTTON]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
DATA_DASHBOARD = f"{DOMAIN}_dashboard"

type FIConfigEntry = ConfigEntry[FIBaseCoordinator]


class DashboardManager:
    """Remembers the dashboard chosen with the build_dashboard action and updates it when accounts change."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.store: Store[dict] = Store(hass, 1, DASHBOARD_STORE_KEY)
        self.url_path: str | None = None
        self.hashes: dict[str, str] | None = None
        self.language: str | None = None
        self.layout = 1
        self.theme = True
        self.debouncer = Debouncer(hass, _LOGGER, cooldown=5, immediate=False, function=self._rebuild)

    async def async_load(self) -> None:
        data = (await self.store.async_load()) or {}
        self.url_path = data.get(ATTR_DASHBOARD)
        # Earlier versions overwrote every tab and stored no hashes.
        self.hashes = data.get("views")
        self.language = data.get(ATTR_LANGUAGE)
        self.layout = data.get("layout", 1)
        self.theme = data.get(ATTR_THEME, True)

    async def async_build(self, url_path: str, reset: bool = False, language: str | None = None,
                          theme: bool | None = None) -> dict:
        from .dashboard import LAYOUT_VERSION, async_build_dashboard

        hashes = self.hashes if url_path == self.url_path else {}
        # Default: the language chosen before, otherwise the Home Assistant language.
        language = language or self.language or ("de" if (self.hass.config.language or "").startswith("de") else "en")
        # The theme is recommended and on unless switched off once; the choice is remembered.
        theme = self.theme if theme is None else theme
        theme_state = "off"
        if theme:
            theme_state = "applied" if await async_install_theme(self.hass) else "not_loaded"
        # A new tab layout reorders the generated tabs once.
        new_hashes, stats = await async_build_dashboard(self.hass, url_path, hashes, reset, language,
                                                        reorder=self.layout < LAYOUT_VERSION,
                                                        theme=THEME_NAME if theme else None)
        self.url_path, self.hashes, self.language, self.layout, self.theme = url_path, new_hashes, language, LAYOUT_VERSION, theme
        await self.store.async_save({ATTR_DASHBOARD: url_path, "views": new_hashes, ATTR_LANGUAGE: language,
                                     "layout": LAYOUT_VERSION, ATTR_THEME: theme})
        return {**stats, "language": language, "theme": theme_state}

    async def _rebuild(self) -> None:
        if not self.url_path:
            return
        try:
            await self.async_build(self.url_path)
        except Exception as err:  # noqa: BLE001 - a missing dashboard must not break the integration
            _LOGGER.warning("Could not update dashboard %s: %s", self.url_path, err)

    @callback
    def schedule(self) -> None:
        if self.url_path:
            self.hass.async_create_task(self.debouncer.async_call())


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    await async_register_frontend(hass)
    manager = DashboardManager(hass)
    await manager.async_load()
    hass.data[DATA_DASHBOARD] = manager

    async def build(call: ServiceCall) -> ServiceResponse:
        return await manager.async_build(call.data[ATTR_DASHBOARD], call.data[ATTR_RESET], call.data.get(ATTR_LANGUAGE),
                                         call.data.get(ATTR_THEME))

    hass.services.async_register(DOMAIN, SERVICE_BUILD_DASHBOARD, build,
                                 schema=vol.Schema({vol.Required(ATTR_DASHBOARD): cv.string,
                                                    vol.Optional(ATTR_RESET, default=False): cv.boolean,
                                                    vol.Optional(ATTR_LANGUAGE): vol.In(["en", "de"]),
                                                    vol.Optional(ATTR_THEME): cv.boolean}),
                                 supports_response=SupportsResponse.OPTIONAL)

    async def backfill(_call: ServiceCall) -> ServiceResponse:
        accounts = []
        for coordinator in list(hass.data.get(DOMAIN).coordinators.values()) if DOMAIN in hass.data else []:
            try:
                if result := await coordinator.async_backfill():
                    accounts.append(result)
            except Exception as err:  # noqa: BLE001 - one account must not stop the others
                _LOGGER.exception("Could not backfill %s", coordinator.config_entry.title)
                accounts.append({"account": coordinator.config_entry.title, "error": str(err)})
        return {"accounts": accounts}

    hass.services.async_register(DOMAIN, SERVICE_BACKFILL_HISTORY, backfill, schema=vol.Schema({}),
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

    if entry.data.get(CONF_DEMO):
        # Keep the sample data current: dates move up to this month on every start.
        await hass.async_add_executor_job(demo.write_demo_files, hass.config.config_dir, dt_util.now().date())
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
