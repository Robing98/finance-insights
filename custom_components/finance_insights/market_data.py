"""Dividend events and benchmarks from external sources.

Providers return plain DividendEvent lists. Response formats follow the public
documentation of each service; fields that a service leaves empty stay None.
"""
from __future__ import annotations

import csv
import io
import logging
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone

import aiohttp

_LOGGER = logging.getLogger(__name__)
TIMEOUT = aiohttp.ClientTimeout(total=20)
# Yahoo rejects requests without a browser-like user agent.
YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}


class ProviderError(Exception):
    """The provider failed for this request."""


class NotAvailable(ProviderError):
    """The plan or key does not include this data (for example a premium endpoint)."""


class RateLimited(ProviderError):
    """The provider's request limit is reached."""


@dataclass
class DividendEvent:
    ex_date: date
    amount: float
    currency: str | None = None
    pay_date: date | None = None
    record_date: date | None = None
    declared_date: date | None = None
    source: str = ""

    def to_json(self) -> dict:
        return {k: (v.isoformat() if isinstance(v, date) else v) for k, v in asdict(self).items()}

    @classmethod
    def from_json(cls, d: dict) -> DividendEvent:
        return cls(ex_date=_date(d["ex_date"]), amount=float(d["amount"]), currency=d.get("currency"),
                   pay_date=_date(d.get("pay_date")), record_date=_date(d.get("record_date")),
                   declared_date=_date(d.get("declared_date")), source=d.get("source", ""))


def _date(value) -> date | None:
    if value in (None, "", "None", "null", "0000-00-00"):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _float(value) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # drop NaN


def normalize_currency(amount: float, currency: str | None) -> tuple[float, str | None]:
    """London quotes in pence (GBX, GBp) become pounds."""
    if currency in ("GBX", "GBp", "GBx"):
        return amount / 100, "GBP"
    return amount, (currency or None) and currency.upper()


async def _get_json(session: aiohttp.ClientSession, url: str, params: dict | None = None, headers=None):
    try:
        async with session.get(url, params=params, headers=headers, timeout=TIMEOUT) as resp:
            if resp.status == 429:
                raise RateLimited(f"HTTP 429 from {url.split('/')[2]}")
            if resp.status in (401, 402, 403):
                raise NotAvailable(f"HTTP {resp.status} from {url.split('/')[2]}")
            if resp.status == 404:
                return None
            if resp.status >= 400:
                raise ProviderError(f"HTTP {resp.status} from {url.split('/')[2]}")
            return await resp.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError) as err:
        raise ProviderError(f"{type(err).__name__} for {url.split('/')[2]}") from err


def _isin_country(isin: str) -> str:
    return isin[:2].upper()


# ---------------------------------------------------------------- providers

class Provider:
    name = ""
    label = ""
    #: Calls per day allowed by the free plan, used as the default budget.
    daily_budget = 20
    #: How far back the provider returns history.
    history_years = 10

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key

    async def lookup(self, session, isin: str, name: str | None) -> str | None:
        raise NotImplementedError

    async def dividends(self, session, symbol: str, since: date) -> list[DividendEvent]:
        raise NotImplementedError


class EODHDProvider(Provider):
    """https://eodhd.com/financial-apis/api-splits-dividends"""
    name, label, daily_budget, history_years = "eodhd", "EODHD", 20, 1
    base = "https://eodhd.com/api"

    async def lookup(self, session, isin, name):
        data = await _get_json(session, f"{self.base}/search/{isin}", {"api_token": self.api_key, "fmt": "json"})
        items = data if isinstance(data, list) else []
        if not items:
            return None
        # Prefer the primary listing, then a listing in the ISIN's home country.
        items.sort(key=lambda i: (not i.get("isPrimary"), (i.get("ISIN") or "") != isin))
        best = items[0]
        return f"{best['Code']}.{best['Exchange']}" if best.get("Code") and best.get("Exchange") else None

    async def dividends(self, session, symbol, since):
        data = await _get_json(session, f"{self.base}/div/{symbol}",
                               {"api_token": self.api_key, "fmt": "json", "from": since.isoformat()})
        events = []
        for d in data if isinstance(data, list) else []:
            amount = _float(d.get("unadjustedValue")) or _float(d.get("value"))
            ex = _date(d.get("date"))
            if ex and amount:
                amount, cur = normalize_currency(amount, d.get("currency"))
                events.append(DividendEvent(ex, amount, cur, _date(d.get("paymentDate")), _date(d.get("recordDate")),
                                            _date(d.get("declarationDate")), self.name))
        return events


class AlphaVantageProvider(Provider):
    """https://www.alphavantage.co/documentation/ (DIVIDENDS, SYMBOL_SEARCH)"""
    name, label, daily_budget, history_years = "alphavantage", "Alpha Vantage", 25, 20
    base = "https://www.alphavantage.co/query"
    regions = {"US": "United States", "GB": "United Kingdom", "DE": "XETRA", "CH": "Switzerland", "FR": "Paris",
               "NL": "Amsterdam", "CA": "Toronto"}

    @staticmethod
    def _check(data):
        if isinstance(data, dict):
            note = data.get("Note") or data.get("Information") or ""
            if "rate limit" in note.lower() or "requests per" in note.lower():
                raise RateLimited(note[:120])
            if "premium" in note.lower():
                raise NotAvailable(note[:120])
            if data.get("Error Message"):
                raise ProviderError(data["Error Message"][:120])
        return data

    async def lookup(self, session, isin, name):
        if not name:
            return None
        data = self._check(await _get_json(session, self.base, {"function": "SYMBOL_SEARCH", "keywords": name,
                                                                 "apikey": self.api_key}))
        matches = (data or {}).get("bestMatches") or []
        region = self.regions.get(_isin_country(isin))
        preferred = [m for m in matches if region and m.get("4. region") == region]
        best = (preferred or matches or [None])[0]
        return best.get("1. symbol") if best else None

    async def dividends(self, session, symbol, since):
        data = self._check(await _get_json(session, self.base, {"function": "DIVIDENDS", "symbol": symbol,
                                                                 "apikey": self.api_key}))
        events = []
        for d in (data or {}).get("data") or []:
            ex, amount = _date(d.get("ex_dividend_date")), _float(d.get("amount"))
            if ex and amount and ex >= since:
                events.append(DividendEvent(ex, amount, None, _date(d.get("payment_date")), _date(d.get("record_date")),
                                            _date(d.get("declaration_date")), self.name))
        return events


class FinnhubProvider(Provider):
    """https://finnhub.io/docs/api/stock-dividends (premium) and /search"""
    name, label, daily_budget, history_years = "finnhub", "Finnhub", 500, 20
    base = "https://finnhub.io/api/v1"

    async def lookup(self, session, isin, name):
        data = await _get_json(session, f"{self.base}/search", {"q": isin, "token": self.api_key})
        results = (data or {}).get("result") or []
        return results[0].get("symbol") if results else None

    async def dividends(self, session, symbol, since):
        data = await _get_json(session, f"{self.base}/stock/dividend",
                               {"symbol": symbol, "from": since.isoformat(), "to": date.today().replace(year=date.today().year + 1).isoformat(),
                                "token": self.api_key})
        if isinstance(data, dict) and data.get("error"):
            raise NotAvailable(str(data["error"])[:120])
        events = []
        for d in data if isinstance(data, list) else []:
            ex = _date(d.get("date") or d.get("exDate"))
            amount = _float(d.get("amount"))
            if ex and amount:
                amount, cur = normalize_currency(amount, d.get("currency"))
                events.append(DividendEvent(ex, amount, cur, _date(d.get("payDate") or d.get("paymentDate")),
                                            _date(d.get("recordDate")), _date(d.get("declarationDate")), self.name))
        return events


class YahooProvider(Provider):
    """Unofficial Yahoo Finance endpoints (the same ones yfinance uses). No key, can break."""
    name, label, daily_budget, history_years = "yahoo", "Yahoo Finance", 200, 10

    async def lookup(self, session, isin, name):
        data = await _get_json(session, "https://query2.finance.yahoo.com/v1/finance/search",
                               {"q": isin, "quotesCount": 5, "newsCount": 0}, YAHOO_HEADERS)
        quotes = [q for q in (data or {}).get("quotes") or [] if q.get("quoteType") in ("EQUITY", "ETF", None)]
        return quotes[0].get("symbol") if quotes else None

    async def dividends(self, session, symbol, since):
        data = await _get_json(session, f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                               {"range": "10y", "interval": "1mo", "events": "div"}, YAHOO_HEADERS)
        result = (((data or {}).get("chart") or {}).get("result") or [None])[0] or {}
        currency = (result.get("meta") or {}).get("currency")
        events = []
        for d in ((result.get("events") or {}).get("dividends") or {}).values():
            ex = datetime.fromtimestamp(int(d["date"]), tz=timezone.utc).date() if d.get("date") else None
            amount = _float(d.get("amount"))
            if ex and amount and ex >= since:
                a, cur = normalize_currency(amount, currency)
                events.append(DividendEvent(ex, a, cur, source=self.name))
        return sorted(events, key=lambda e: e.ex_date)


PROVIDERS: dict[str, type[Provider]] = {p.name: p for p in (EODHDProvider, AlphaVantageProvider, FinnhubProvider, YahooProvider)}


def merge_events(primary: list[DividendEvent], history: list[DividendEvent], days: int = 5) -> list[DividendEvent]:
    """Primary events win (they carry pay dates); history fills older years."""
    out = list(primary)
    for h in history:
        if not any(abs((h.ex_date - p.ex_date).days) <= days for p in primary):
            out.append(h)
    return sorted(out, key=lambda e: e.ex_date)


# ---------------------------------------------------------------- ECB data

ECB = "https://data-api.ecb.europa.eu/service/data"
SERIES = {
    "ecb_deposit_rate": "FM/B.U2.EUR.4F.KR.DFR.LEV",
    "inflation": "ICP/M.U2.N.000000.4.ANR",
}


def parse_ecb_csv(text: str) -> list[tuple[str, float]]:
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        value = _float(r.get("OBS_VALUE"))
        if r.get("TIME_PERIOD") and value is not None:
            rows.append((r["TIME_PERIOD"], value))
    return sorted(rows)


async def ecb_series(session, key: str, start: str) -> list[tuple[str, float]]:
    try:
        async with session.get(f"{ECB}/{key}", params={"startPeriod": start, "format": "csvdata"}, timeout=TIMEOUT) as resp:
            if resp.status >= 400:
                raise ProviderError(f"HTTP {resp.status} from ECB")
            return parse_ecb_csv(await resp.text())
    except (aiohttp.ClientError, TimeoutError) as err:
        raise ProviderError(f"{type(err).__name__} for ECB") from err


async def ecb_fx(session, currencies: set[str], start: str) -> dict[str, float]:
    """Latest reference rate per currency: units of that currency per euro."""
    wanted = sorted(c for c in currencies if c and c != "EUR" and re.fullmatch(r"[A-Z]{3}", c))
    if not wanted:
        return {}
    rows = []
    try:
        async with session.get(f"{ECB}/EXR/D.{'+'.join(wanted)}.EUR.SP00.A",
                               params={"startPeriod": start, "format": "csvdata"}, timeout=TIMEOUT) as resp:
            if resp.status >= 400:
                raise ProviderError(f"HTTP {resp.status} from ECB")
            rows = list(csv.DictReader(io.StringIO(await resp.text())))
    except (aiohttp.ClientError, TimeoutError) as err:
        raise ProviderError(f"{type(err).__name__} for ECB") from err
    latest: dict[str, tuple[str, float]] = {}
    for r in rows:
        cur, value = r.get("CURRENCY"), _float(r.get("OBS_VALUE"))
        if cur and value and (cur not in latest or r["TIME_PERIOD"] > latest[cur][0]):
            latest[cur] = (r["TIME_PERIOD"], value)
    return {c: v for c, (_, v) in latest.items()}
