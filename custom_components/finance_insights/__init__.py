"""Finance Insights: brokerage and bank accounts as Home Assistant sensors."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.requirements import RequirementsNotFound, async_process_requirements

from .const import CONF_USE_FINTS, CONF_USE_PYTR, DOMAIN, FINTS_REQUIREMENT, PYTR_REQUIREMENT
from .coordinator import COORDINATORS, FIBaseCoordinator, FinanceHub, account_type

PLATFORMS = [Platform.SENSOR, Platform.BUTTON]

type FIConfigEntry = ConfigEntry[FIBaseCoordinator]


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
    return True


async def _reload_on_options(hass: HomeAssistant, entry: FIConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: FIConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok and DOMAIN in hass.data:
        hass.data[DOMAIN].unregister(entry.entry_id)
    return ok
