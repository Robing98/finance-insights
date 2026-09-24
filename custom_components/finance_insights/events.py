"""Home Assistant events for new bookings and new recurring payments, for automations."""
from __future__ import annotations

import hashlib
from datetime import date, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from . import watch_core
from .const import CONF_OWNER, DOMAIN

EVENT_TRANSACTION = f"{DOMAIN}_transaction"
EVENT_RECURRING = f"{DOMAIN}_new_recurring"
EVENT_HOLDING = f"{DOMAIN}_holding_event"
WINDOW_DAYS = 45        # older bookings never fire, for example from a freshly imported export
MAX_EVENTS = 50         # per update, so a large import does not flood automations


def tr_items(rows: list[dict]) -> list[dict]:
    """Trade Republic rows as event payloads."""
    out = []
    for r in rows:
        key = r.get("id") or hashlib.sha1("|".join(str(r.get(k)) for k in (
            "datetime", "type", "amount", "name", "symbol", "shares")).encode()).hexdigest()[:16]
        amount = (r.get("income_value") if r["bucket"] == "income" else r.get("amount")) or 0.0
        out.append(dict(id=key, date=date.fromisoformat(r["date"]), amount=round(float(amount), 2), kind=r["bucket"],
                        type=r["type"], name=r.get("name") or "", category=r.get("income_kind") or r.get("category") or "",
                        symbol=r.get("symbol")))
    return out


def bank_items(rows: list[dict], today: date) -> list[dict]:
    """Booked bank rows as event payloads. Pending bookings wait until they are booked."""
    return [dict(id=r["id"], date=r["date"], amount=round(r["amount"], 2), kind=r["kind"], type=r.get("booking_text") or "",
                 name=r.get("merchant") or r.get("counterparty") or "", category=r.get("income_kind") or r.get("category") or "",
                 purpose=(r.get("purpose") or "")[:140])
            for r in rows if not r.get("pending") and r["date"] <= today]


def _base(entry: ConfigEntry) -> dict:
    return {"entry_id": entry.entry_id, "account": entry.title, "owner": entry.options.get(CONF_OWNER)}


class WatchEmitter:
    """Keeps what the last run saw of a portfolio, and announces what changed since.

    The first run only records, so connecting an account fires nothing.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass, self.entry = hass, entry
        self.store: Store = Store(hass, 1, f"{DOMAIN}.watch_{entry.entry_id}")
        self.state: dict | None = None

    async def async_process(self, result: dict, rows: list[dict], dividend_events: dict, today: date) -> dict:
        """Returns the feed for the sensors."""
        if self.state is None:
            self.state = await self.store.async_load() or {}
        out = watch_core.analyze_watch(result, rows, dividend_events, self.state, today)
        for item in out["new"][:MAX_EVENTS]:
            self.hass.bus.async_fire(EVENT_HOLDING, {**_base(self.entry),
                                                     **{k: v for k, v in item.items() if k != "id"}})
        if out["state"] != self.state:
            # Most updates change nothing here, and writing the same state every few minutes
            # wears out the card a Home Assistant box often runs on.
            self.state = out["state"]
            await self.store.async_save(self.state)
        return out["view"]


class EventEmitter:
    """Remembers which bookings were announced. The first run only records them, so setup fires nothing."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass, self.entry = hass, entry
        self.store: Store = Store(hass, 1, f"{DOMAIN}.events_{entry.entry_id}")
        self.seen: set[str] | None = None
        self.recurring: set[str] | None = None

    async def _load(self) -> bool:
        if self.seen is not None:
            return True
        data = await self.store.async_load()
        self.seen = set(data["ids"]) if data else set()
        self.recurring = set(data.get("recurring", [])) if data else None
        return data is not None

    def _base(self) -> dict:
        return _base(self.entry)

    async def async_process(self, items: list[dict], today: date, recurring: list[dict] | None = None) -> int:
        """Fire events for new items; returns how many fired."""
        existed = await self._load()
        cutoff = today - timedelta(days=WINDOW_DAYS)
        recent = [i for i in items if i["date"] >= cutoff]
        fired = 0
        if existed:
            new = sorted((i for i in recent if i["id"] not in self.seen), key=lambda i: i["date"])[-MAX_EVENTS:]
            for i in new:
                self.hass.bus.async_fire(EVENT_TRANSACTION, {**self._base(), **{k: v for k, v in i.items() if k != "id"},
                                                             "date": i["date"].isoformat()})
            fired = len(new)
        self.seen = {i["id"] for i in recent}
        if recurring is not None:
            names = {r["name"] for r in recurring}
            if self.recurring is not None:
                for r in recurring:
                    if r["name"] not in self.recurring:
                        self.hass.bus.async_fire(EVENT_RECURRING, {**self._base(), **{k: r[k] for k in (
                            "name", "category", "cadence", "amount", "monthly", "next_date")}})
            self.recurring = names
        await self.store.async_save({"ids": sorted(self.seen), "recurring": sorted(self.recurring or [])})
        return fired
