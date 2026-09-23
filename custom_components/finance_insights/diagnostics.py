"""Diagnostics download, so an issue report needs no files from .storage.

Everything identifying is removed: credentials, account numbers, names, and the bookings
themselves. What is left describes the shape of the data, which is what a bug report needs.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_BLZ, CONF_IBAN, CONF_LOGIN, CONF_PHONE, CONF_PIN, CONF_PRODUCT_ID, CONF_SERVER
from .coordinator import account_type
from . import vault

REDACT_DATA = {CONF_PIN, CONF_PRODUCT_ID, CONF_LOGIN, CONF_IBAN, CONF_BLZ, CONF_PHONE, CONF_SERVER}
REDACT_OPTIONS = {"dividend_api_key", "owner", "shared_with", "members", "transfer_keywords", "offset_rules"}


def _shape(value: Any) -> Any:
    """Describe a value instead of reporting it. Amounts are as private as names."""
    if isinstance(value, dict):
        return {"type": "dict", "keys": sorted(str(k) for k in value)[:40]}
    if isinstance(value, list):
        return {"type": "list", "length": len(value),
                "item_keys": sorted(value[0])[:40] if value and isinstance(value[0], dict) else None}
    return {"type": type(value).__name__, "set": value is not None}


def _shapes(result: Any) -> dict:
    return {key: _shape(value) for key, value in result.items()} if isinstance(result, dict) else {}


def _meta(result: dict | None) -> dict:
    """The part worth reporting: counts, file types, and the error texts."""
    meta = dict((result or {}).get("meta") or {})
    files = meta.get("csv_files")
    if isinstance(files, list):
        meta["csv_files"] = {"count": len(files), "suffixes": sorted({f.rpartition(".")[2] for f in files})}
    return meta


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """No amounts, no names, no account numbers: which data exists, how much, and what failed."""
    coordinator = getattr(entry, "runtime_data", None)
    result = getattr(coordinator, "data", None)
    sync = getattr(coordinator, "sync", None)
    return {
        "entry": {
            "type": account_type(entry),
            "data": async_redact_data(dict(entry.data), REDACT_DATA),
            "options": async_redact_data(dict(entry.options), REDACT_OPTIONS),
            "pin_stored_on_disk": not vault.asks_for_pin(entry),
        },
        "sync": {k: v for k, v in vars(sync).items() if k != "force"} if sync is not None else None,
        "meta": _meta(result),
        "summary": _shapes((result or {}).get("summary")),
        "result": _shapes(result),
    }
