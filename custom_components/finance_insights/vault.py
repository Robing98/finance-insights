"""PINs that are never written to disk.

With "Ask for the PIN after a restart" switched on, the PIN exists only in memory, for as long
as Home Assistant runs. After a restart the account asks for it again through the usual
notification. That is the only way to keep a PIN off the disk in a service that reconnects on
its own: anything the integration could decrypt unattended, an attacker with the same files
could decrypt too.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from .const import CONF_ASK_PIN, CONF_PIN, DOMAIN

DATA_PINS = f"{DOMAIN}_pins"


@callback
def remember(hass: HomeAssistant, entry_id: str, pin: str) -> None:
    hass.data.setdefault(DATA_PINS, {})[entry_id] = pin


@callback
def forget(hass: HomeAssistant, entry_id: str) -> None:
    hass.data.get(DATA_PINS, {}).pop(entry_id, None)


@callback
def asks_for_pin(entry: ConfigEntry) -> bool:
    return bool(entry.options.get(CONF_ASK_PIN))


@callback
def pin(hass: HomeAssistant, entry: ConfigEntry) -> str | None:
    """The PIN of this account, from memory when it is not stored on disk."""
    if asks_for_pin(entry):
        return hass.data.get(DATA_PINS, {}).get(entry.entry_id)
    return entry.data.get(CONF_PIN)
