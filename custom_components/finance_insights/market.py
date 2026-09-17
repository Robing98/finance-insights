"""Fetch and cache dividend events and benchmarks within the providers' daily limits."""
from __future__ import annotations

import csv
import io
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .market_data import (
    PROVIDERS, SERIES, DividendEvent, NotAvailable, ProviderError, RateLimited, YahooProvider, ecb_fx, ecb_series,
    merge_events,
)

_LOGGER = logging.getLogger(__name__)
SYMBOLS_FILE = "symbols.csv"
NO_DIVIDENDS_RECHECK = timedelta(days=7)
LOOKUP_RETRY = timedelta(days=30)
FAILURE_BACKOFF = timedelta(hours=6)


def read_symbols(path: Path) -> dict[str, str]:
    """isin,symbol overrides for the dividend provider (comma or semicolon)."""
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8-sig")
    delimiter = ";" if text.splitlines()[0].count(";") > text.splitlines()[0].count(",") else ","
    return {r["isin"].strip().upper(): r["symbol"].strip() for r in csv.DictReader(io.StringIO(text), delimiter=delimiter)
            if r.get("isin") and r.get("symbol")}


class MarketData:
    def __init__(self, hass: HomeAssistant, entry_id: str, folder: Path, *, provider: str | None, api_key: str | None,
                 yahoo_fallback: bool, benchmarks: bool, refresh_hours: int, daily_budget: int | None = None) -> None:
        self.hass = hass
        self.folder = folder
        self.store: Store[dict] = Store(hass, 1, f"finance_insights.market_{entry_id}")
        cls = PROVIDERS.get(provider or "")
        self.primary = cls(api_key) if cls and cls is not YahooProvider else None
        self.yahoo = YahooProvider() if yahoo_fallback or provider == "yahoo" else None
        self.benchmarks_enabled = benchmarks
        self.refresh = timedelta(hours=refresh_hours)
        self.budget = {p.name: (daily_budget if p is self.primary and daily_budget else p.daily_budget)
                       for p in (self.primary, self.yahoo) if p}
        self.data: dict = {}
        self.loaded = False
        self.status: dict = {}

    # ------------------------------------------------------------ cache helpers

    def events(self) -> dict[str, list[DividendEvent]]:
        return {isin: [DividendEvent.from_json(e) for e in item.get("events", [])]
                for isin, item in self.data.get("events", {}).items()}

    @property
    def fx(self) -> dict[str, float]:
        return self.data.get("fx", {})

    @property
    def benchmarks(self) -> dict[str, list[tuple[str, float]]]:
        return {k: [tuple(x) for x in v] for k, v in self.data.get("benchmarks", {}).items()}

    def _calls_left(self, provider) -> int:
        today = dt_util.now().date().isoformat()
        used = self.data.setdefault("calls", {}).setdefault(provider.name, {})
        for day in [d for d in used if d != today]:
            used.pop(day)
        return self.budget[provider.name] - used.get(today, 0)

    def _count(self, provider) -> None:
        today = dt_util.now().date().isoformat()
        used = self.data.setdefault("calls", {}).setdefault(provider.name, {})
        used[today] = used.get(today, 0) + 1

    # ------------------------------------------------------------ fetching

    async def _symbol(self, session, provider, isin: str, name: str | None, overrides: dict[str, str]) -> str | None:
        if provider is self.primary and isin in overrides:
            return overrides[isin]
        cache = self.data.setdefault("symbols", {}).setdefault(provider.name, {})
        cached = cache.get(isin)
        if cached and cached["symbol"]:
            return cached["symbol"]
        if cached and datetime.fromisoformat(cached["checked"]) > dt_util.utcnow() - LOOKUP_RETRY:
            return None
        if self._calls_left(provider) <= 0:
            raise RateLimited("daily budget used")
        self._count(provider)
        symbol = await provider.lookup(session, isin, name)
        cache[isin] = {"symbol": symbol or "", "checked": dt_util.utcnow().isoformat()}
        return symbol

    async def _fetch(self, session, provider, isin, name, overrides, since) -> list[DividendEvent] | None:
        symbol = await self._symbol(session, provider, isin, name, overrides)
        if not symbol:
            return None
        if self._calls_left(provider) <= 0:
            raise RateLimited("daily budget used")
        self._count(provider)
        return await provider.dividends(session, symbol, since)

    def _due(self, isin: str) -> bool:
        failed = self.data.get("failed", {}).get(isin)
        if failed and dt_util.utcnow() - datetime.fromisoformat(failed) < FAILURE_BACKOFF:
            return False
        item = self.data.get("events", {}).get(isin)
        if not item:
            return True
        age = dt_util.utcnow() - datetime.fromisoformat(item["fetched"])
        return age >= (self.refresh if item.get("events") else max(self.refresh, NO_DIVIDENDS_RECHECK))

    async def async_update(self, instruments: list[tuple[str, str | None]]) -> None:
        """instruments: (isin, name) of held stocks and funds plus watchlist entries."""
        if not self.loaded:
            self.data = await self.store.async_load() or {}
            self.loaded = True
        session = async_get_clientsession(self.hass)
        overrides = await self.hass.async_add_executor_job(read_symbols, self.folder / SYMBOLS_FILE)
        today = dt_util.now().date()
        errors: list[str] = []
        stopped: set[str] = set()
        cache = self.data.setdefault("events", {})
        due = sorted((i for i in instruments if self._due(i[0])),
                     key=lambda i: cache.get(i[0], {}).get("fetched", ""))
        for isin, name in due:
            primary_events = history = None
            for provider in (self.primary, self.yahoo):
                if provider is None or provider.name in stopped:
                    continue
                if provider is self.yahoo and primary_events and (self.primary.history_years >= 5):
                    continue  # the primary provider already has enough history
                since = today - timedelta(days=365 * min(provider.history_years, 10))
                try:
                    got = await self._fetch(session, provider, isin, name, overrides, since)
                except RateLimited as err:
                    stopped.add(provider.name)
                    errors.append(f"{provider.label}: {err}")
                    continue
                except NotAvailable as err:
                    stopped.add(provider.name)
                    errors.append(f"{provider.label}: not included in your plan ({err})")
                    continue
                except ProviderError as err:
                    errors.append(f"{provider.label} {isin}: {err}")
                    continue
                except Exception as err:  # noqa: BLE001 - an unexpected response must not stop the other instruments
                    _LOGGER.debug("%s failed for %s", provider.label, isin, exc_info=True)
                    errors.append(f"{provider.label} {isin}: {type(err).__name__}")
                    continue
                if provider is self.primary:
                    primary_events = got
                else:
                    history = got
            if primary_events is None and history is None:
                # Nothing fetched: keep the cache and try again after a pause.
                self.data.setdefault("failed", {})[isin] = dt_util.utcnow().isoformat()
                continue
            self.data.get("failed", {}).pop(isin, None)
            merged = merge_events(primary_events or [], history or [])
            cache[isin] = {"fetched": dt_util.utcnow().isoformat(), "name": name,
                           "sources": sorted({e.source for e in merged}), "events": [e.to_json() for e in merged]}

        if self.benchmarks_enabled:
            await self._update_benchmarks(session, today, errors)
        self.status = {"provider": self.primary.label if self.primary else None,
                       "yahoo_fallback": self.yahoo is not None,
                       "calls_today": {name: self.budget[name] - self._calls_left(p)
                                       for name, p in (((p.name, p) for p in (self.primary, self.yahoo) if p))},
                       "instruments": len(instruments), "cached": len(cache), "errors": errors[-10:]}
        self.store.async_delay_save(lambda: self.data, 5)

    async def _update_benchmarks(self, session, today: date, errors: list[str]) -> None:
        fetched = self.data.get("benchmarks_fetched")
        currencies = {e.currency for events in self.events().values() for e in events if e.currency}
        fresh = fetched and dt_util.utcnow() - datetime.fromisoformat(fetched) < timedelta(hours=12)
        if fresh and currencies <= set(self.fx) | {"EUR"}:
            return
        start = (today - timedelta(days=3 * 365)).isoformat()
        series = self.data.setdefault("benchmarks", {})
        try:
            for key, flow in SERIES.items():
                series[key] = await ecb_series(session, flow, start[:7] if key == "inflation" else start)
            self.data["fx"] = await ecb_fx(session, currencies, (today - timedelta(days=10)).isoformat())
            self.data["benchmarks_fetched"] = dt_util.utcnow().isoformat()
        except ProviderError as err:
            errors.append(f"ECB: {err}")
