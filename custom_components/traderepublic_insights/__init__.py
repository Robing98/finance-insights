"""Trade Republic Insights: portfolio, income, and spending sensors from Trade Republic data."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.requirements import RequirementsNotFound, async_process_requirements

from .const import CONF_USE_PYTR, DOMAIN, PYTR_REQUIREMENT
from .coordinator import TRCoordinator

PLATFORMS = [Platform.SENSOR, Platform.BUTTON]

type TRConfigEntry = ConfigEntry[TRCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: TRConfigEntry) -> bool:
    if entry.data.get(CONF_USE_PYTR):
        try:
            await async_process_requirements(hass, DOMAIN, [PYTR_REQUIREMENT])
        except RequirementsNotFound as err:
            raise ConfigEntryNotReady(f"Could not install {PYTR_REQUIREMENT}") from err

    coordinator = TRCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_reload_on_options))
    return True


async def _reload_on_options(hass: HomeAssistant, entry: TRConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: TRConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
