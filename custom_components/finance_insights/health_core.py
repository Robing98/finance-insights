"""Descriptive checks on the shape of a portfolio.

Pure Python without Home Assistant imports, computed from data the integration already
has. Nothing is fetched for it.

Every check states a measured figure and the threshold it is compared with. A check is a
description, not advice: concentration, cash share, and fees are facts about the account,
and what to do about them is the owner's decision. Nothing here rates a position, scores a
portfolio, or suggests a trade.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

OK, NOTE, WATCH = "ok", "note", "watch"
#: Thresholds as (note, watch). A figure at or above the first is a note, at or above the second a watch.
LIMITS = {
    "concentration": (15.0, 25.0),
    "top5": (60.0, 80.0),
    "cash": (15.0, 30.0),
    "dividend_concentration": (30.0, 50.0),
    "foreign_dividends": (30.0, None),
    "fees": (1.0, 2.0),
}
#: A price from an old trade is a guess about today's value.
STALE_DAYS = 30


def _level(value: float | None, limits: tuple[float, float | None]) -> str:
    note, watch = limits
    if value is None:
        return OK
    if watch is not None and value >= watch:
        return WATCH
    return NOTE if value >= note else OK


def _check(key: str, level: str, value=None, unit: str | None = None, **extra) -> dict:
    """unit: what `value` is measured in, so a table can print a number and its unit apart."""
    return dict(key=key, level=level, value=value, unit=unit, **extra)


def _concentration(holdings: list[dict], checks: list[dict]) -> dict:
    priced = [h for h in holdings if h.get("value")]
    if not priced:
        return {}
    top = max(priced, key=lambda h: h["value"])
    largest = round(top["weight_pct"], 1)
    checks.append(_check("concentration", _level(largest, LIMITS["concentration"]), largest, "%",
                         limit=LIMITS["concentration"][0], name=top["name"]))
    out = dict(largest_pct=largest, largest_name=top["name"], positions=len(holdings))
    if len(priced) > 5:
        top5 = round(sum(h["weight_pct"] for h in sorted(priced, key=lambda h: -h["value"])[:5]), 1)
        checks.append(_check("top5", _level(top5, LIMITS["top5"]), top5, "%", limit=LIMITS["top5"][0], count=5))
        out["top5_pct"] = top5
    return out


def _cash(summary: dict, checks: list[dict]) -> dict:
    cash, value = summary.get("cash") or 0.0, summary.get("holdings_value") or 0.0
    total = cash + value
    if total <= 0 or cash <= 0:
        return {}
    share = round(cash / total * 100, 1)
    checks.append(_check("cash", _level(share, LIMITS["cash"]), share, "%", limit=LIMITS["cash"][0], amount=round(cash, 2)))
    return dict(cash_pct=share)


def _prices(holdings: list[dict], today: date, checks: list[dict]) -> dict:
    """Positions without a price, and positions valued from an old trade."""
    unpriced = [h for h in holdings if h.get("value") is None]
    if unpriced:
        checks.append(_check("unpriced", WATCH, len(unpriced), cost=round(sum(h["cost"] for h in unpriced), 2),
                             names=[h["name"] for h in unpriced][:10]))
    stale = []
    for h in holdings:
        source = str(h.get("price_source") or "")
        traded = source.startswith("last trade ") and source.rsplit(" ", 1)[-1]
        if traded and traded < (today - timedelta(days=STALE_DAYS)).isoformat():
            stale.append(h)
    if stale:
        checks.append(_check("stale_prices", NOTE, len(stale), days=STALE_DAYS,
                             names=[h["name"] for h in stale][:10]))
    return dict(unpriced=len(unpriced), stale_prices=len(stale))


def _dividends(dividends: dict, checks: list[dict]) -> dict:
    """Where the expected dividend income comes from, and in which currency it is paid."""
    stocks = [s for s in dividends.get("stocks") or [] if s.get("annual_income")]
    total = sum(s["annual_income"] for s in stocks)
    out: dict = {}
    if total <= 0:
        return out
    top = max(stocks, key=lambda s: s["annual_income"])
    share = round(top["annual_income"] / total * 100, 1)
    checks.append(_check("dividend_concentration", _level(share, LIMITS["dividend_concentration"]), share, "%",
                         limit=LIMITS["dividend_concentration"][0], name=top["name"]))
    out["dividend_top_pct"] = share

    by_currency: dict[str, float] = defaultdict(float)
    for s in stocks:
        by_currency[s.get("currency") or "EUR"] += s["annual_income"]
    foreign = round(sum(v for c, v in by_currency.items() if c != "EUR") / total * 100, 1)
    checks.append(_check("foreign_dividends", _level(foreign, LIMITS["foreign_dividends"]), foreign, "%",
                         limit=LIMITS["foreign_dividends"][0]))
    out["foreign_dividends_pct"] = foreign
    out["by_currency"] = {c: round(v, 2) for c, v in sorted(by_currency.items(), key=lambda kv: -kv[1])}
    return out


def _fees(rows: list[dict], today: date, checks: list[dict]) -> dict:
    """Order fees of the last twelve months against what was bought in them."""
    since = (today - timedelta(days=365)).isoformat()
    trades = [r for r in rows if r.get("bucket") == "trade" and r["date"] > since]
    fees = sum(abs(r.get("fee") or 0.0) for r in trades)
    bought = -sum(r.get("amount") or 0.0 for r in trades if (r.get("shares") or 0) > 0)
    if bought <= 0 or fees <= 0:
        return {}
    share = round(fees / bought * 100, 2)
    checks.append(_check("fees", _level(share, LIMITS["fees"]), share, "%", limit=LIMITS["fees"][0],
                         amount=round(fees, 2), trades=len(trades)))
    return dict(fees_12m=round(fees, 2), fees_12m_pct=share)


def analyze_health(result: dict, rows: list[dict], today: date) -> dict:
    """result: tr_core.analyze() output, including the dividend analysis when it ran."""
    holdings = result.get("holdings") or []
    checks: list[dict] = []
    out: dict = {}
    if not holdings:
        return dict(checks=[], watch=0, notes=0, positions=0)
    out.update(_concentration(holdings, checks))
    out.update(_cash(result.get("summary") or {}, checks))
    out.update(_prices(holdings, today, checks))
    out.update(_dividends(result.get("dividends") or {}, checks))
    out.update(_fees(rows, today, checks))

    allocation: dict[str, float] = defaultdict(float)
    for h in holdings:
        allocation[h.get("asset_class") or "OTHER"] += h.get("value") or 0.0
    order = {WATCH: 0, NOTE: 1, OK: 2}
    checks.sort(key=lambda c: (order[c["level"]], c["key"]))
    return dict(
        checks=checks, watch=sum(1 for c in checks if c["level"] == WATCH),
        notes=sum(1 for c in checks if c["level"] == NOTE),
        allocation={k: round(v, 2) for k, v in sorted(allocation.items(), key=lambda kv: -kv[1])},
        **out,
    )
