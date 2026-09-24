"""Events on the positions you hold: dividend announcements, changes, and corporate actions.

Pure Python without Home Assistant imports. Everything here is built from data the
integration already has, the dividend events of the provider you configured and the
broker's own bookings. Nothing is fetched for this, and no holding leaves your system.

The module reports what happened to what you own. It does not rate a position, it does
not compare one to another, and it never suggests a trade.
"""
from __future__ import annotations

import hashlib
from datetime import date, timedelta

from .market_data import DividendEvent

#: Below this a changed payment counts as unchanged: rounding, fractions of a cent, and
#: exchange rate noise move an amount by a fraction of a percent without anything happening.
CHANGE_PCT = 2.0
#: A payment counts as late once this much of the usual gap between payments has passed.
LATE_FACTOR = 1.6
#: History the provider only now returns is not news. Events older than this are recorded silently.
NEWS_DAYS = 30
#: How long an entry stays in the feed, and how many entries are kept at most.
LOG_DAYS = 180
LOG_MAX = 100
#: An entry counts towards the sensor's state for this long.
RECENT_DAYS = 30

KIND_ANNOUNCED = "dividend_announced"
KIND_RAISED = "dividend_raised"
KIND_CUT = "dividend_cut"
KIND_LATE = "dividend_late"
KIND_CORPORATE = "corporate_action"
KIND_SPLIT = "split"
#: Types the broker books as a corporate action, and how they are reported.
ROW_KINDS = {"SPLIT": KIND_SPLIT}


def _d(value) -> date | None:
    if value is None or isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _row_id(row: dict) -> str:
    """The broker's own id when it has one, otherwise the booking's content."""
    if row.get("id"):
        return str(row["id"])
    raw = "|".join(str(row.get(k)) for k in ("datetime", "type", "symbol", "shares", "amount", "name"))
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def _change_kind(change_pct: float | None) -> str:
    if change_pct is None or abs(change_pct) <= CHANGE_PCT:
        return KIND_ANNOUNCED
    return KIND_RAISED if change_pct > 0 else KIND_CUT


def _dividend_items(held: dict[str, str], events: dict[str, list[DividendEvent]], known: dict[str, dict],
                    today: date) -> tuple[list[dict], dict[str, dict]]:
    """New dividend events per holding, compared with what was already recorded."""
    items: list[dict] = []
    fingerprints: dict[str, dict] = {}
    oldest_news = today - timedelta(days=NEWS_DAYS)
    for isin, name in held.items():
        evs = sorted(events.get(isin) or [], key=lambda e: e.ex_date)
        if not evs:
            continue
        fingerprints[isin] = {e.ex_date.isoformat(): round(e.amount, 6) for e in evs}
        seen = known.get(isin)
        if not seen:
            continue  # a position whose dividends were never recorded: this run records them
        for event in evs:
            key = event.ex_date.isoformat()
            if key in seen or event.ex_date < oldest_news:
                continue
            # Compare with the payment before it in the same currency, so a switched
            # reporting currency is not read as a cut.
            before = [e for e in evs if e.ex_date < event.ex_date and e.currency == event.currency and e.amount]
            change = (event.amount / before[-1].amount - 1) * 100 if before else None
            items.append(dict(
                id=f"div:{isin}:{key}", date=key, kind=_change_kind(change), isin=isin, name=name,
                amount=round(event.amount, 6), currency=event.currency,
                previous=round(before[-1].amount, 6) if before else None,
                change_pct=round(change, 1) if change is not None else None,
                pay_date=event.pay_date.isoformat() if event.pay_date else None,
            ))
    return items, fingerprints


def _late_items(stocks: list[dict], events: dict[str, list[DividendEvent]], held: dict[str, str],
                today: date) -> list[dict]:
    """Holdings that paid on a rhythm and have now missed it.

    A late payment is not a cut. It says the usual gap has passed without a new date,
    which happens when a company skips, postpones, or simply announces late.
    """
    items = []
    for stock in stocks:
        isin, last = stock.get("isin"), _d(stock.get("last_ex_date"))
        gap = stock.get("gap_days")
        if not stock.get("held") or isin not in held or not last or not gap:
            continue
        if any(e.ex_date > last for e in events.get(isin) or []):
            continue  # the next date is already known
        due = last + timedelta(days=round(gap * LATE_FACTOR))
        if due > today:
            continue
        items.append(dict(id=f"late:{isin}:{last.isoformat()}", date=due.isoformat(), kind=KIND_LATE, isin=isin,
                          name=stock.get("name") or isin, amount=None, currency=None, previous=None,
                          change_pct=None, last_ex_date=last.isoformat(), gap_days=round(gap)))
    return items


def _corporate_items(rows: list[dict], seen: set[str], cutoff: str) -> tuple[list[dict], set[str]]:
    """Splits, swaps, spin-offs, and deliveries the broker booked recently."""
    items, current = [], set()
    for row in rows:
        if row.get("bucket") != "corporate" or row["date"] < cutoff:
            continue
        rid = _row_id(row)
        current.add(rid)
        if rid in seen:
            continue
        items.append(dict(id=f"ca:{rid}", date=row["date"], kind=ROW_KINDS.get(row["type"], KIND_CORPORATE),
                          isin=row.get("symbol"), name=row.get("name") or row.get("symbol") or "",
                          amount=None, currency=None, previous=None, change_pct=None,
                          booking=row["type"], shares=row.get("shares")))
    return items, current


def analyze_watch(result: dict, rows: list[dict], events: dict[str, list[DividendEvent]], state: dict | None,
                  today: date, *, ex_days: int = 21) -> dict:
    """result: tr_core.analyze() output including the dividend analysis. state: what the last run recorded.

    Returns {"view", "state", "new"}. The first run records everything and reports nothing,
    so connecting an account does not produce a feed full of old news.
    """
    state = state or {}
    # An account whose first run found neither dividends nor corporate actions still ran.
    first_run = not state.get("version")
    held = {h["symbol"]: h["name"] for h in result.get("holdings") or []}
    dividends = result.get("dividends") or {}
    cutoff = (today - timedelta(days=LOG_DAYS)).isoformat()

    items, fingerprints = _dividend_items(held, events, state.get("dividends") or {}, today)
    corporate, seen_rows = _corporate_items(rows, set(state.get("rows") or []), cutoff)
    items += corporate
    items += _late_items(dividends.get("stocks") or [], events, held, today)

    logged = {i["id"]: i for i in state.get("log") or [] if i.get("date", "") > cutoff}
    new = [i for i in items if i["id"] not in logged] if not first_run else []
    for item in new:
        logged[item["id"]] = item
    log = sorted(logged.values(), key=lambda i: (i["date"], i["name"]), reverse=True)[:LOG_MAX]

    recent = (today - timedelta(days=RECENT_DAYS)).isoformat()
    horizon = (today + timedelta(days=ex_days)).isoformat()
    upcoming = [u for u in dividends.get("upcoming") or []
                if u["isin"] in held and (u.get("next_ex_date") or u.get("next_pay_date") or "") <= horizon]
    next_ex = next((u for u in upcoming if (u.get("next_ex_date") or "") >= today.isoformat()), None)
    view = dict(
        items=log, upcoming=upcoming, count=sum(1 for i in log if i["date"] > recent),
        changes=sum(1 for i in log if i["date"] > recent and i["kind"] in (KIND_RAISED, KIND_CUT, KIND_LATE)),
        next_ex=next_ex, next_ex_date=next_ex.get("next_ex_date") if next_ex else None,
    )
    return dict(view=view, new=new,
                state=dict(version=1, dividends=fingerprints, rows=sorted(seen_rows), log=log))
