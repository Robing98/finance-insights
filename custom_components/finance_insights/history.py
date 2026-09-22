"""Daily history rebuilt from the imported exports, for the statistics backfill.

The exports reach back further than the sensors do, so these series fill the gap before
the integration was installed. Everything here comes from booked amounts. What a holding
was worth on a past day is not in any export, so no series here claims one: holdings
appear at cost.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from .tr_core import Ledger, z


def _days(first: date, last: date):
    day = first
    while day <= last:
        yield day
        day += timedelta(days=1)


def _to_date(value: str | date) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value[:10])


def broker_history(rows: list[dict], today: date) -> tuple[list[dict], list[str]]:
    """Daily cash, net contributions and cost basis from Trade Republic rows.

    Returns the series and the names of positions that arrived without a price, whose
    cost basis is unknown and therefore counts as zero.
    """
    rows = [r for r in rows if _to_date(r["date"]) <= today]
    if not rows:
        return [], []
    by_day: dict[date, list[dict]] = defaultdict(list)
    for row in rows:
        by_day[_to_date(row["date"])].append(row)

    unpriced = sorted({r["name"] or r["symbol"] for r in rows
                       if r["type"] == "FREE_RECEIPT" and z(r["shares"]) and not z(r["price"])})
    ledger, cash, contributions, series = Ledger(), 0.0, 0.0, []
    for day in _days(_to_date(rows[0]["date"]), today):
        today_rows = by_day.get(day)
        if today_rows:
            ledger.run(today_rows)
            for row in today_rows:
                cash += row["cash"]
                if row["bucket"] in ("deposit", "withdrawal"):
                    contributions += z(row["amount"])
                elif row["bucket"] == "spending":
                    contributions += z(row["amount"]) + z(row["fee"])
        series.append({"date": day, "cash": round(cash, 2), "contributions": round(contributions, 2),
                       "cost": round(sum(p["cost"] for p in ledger.pos.values()), 2)})
    return series, unpriced


def bank_history(rows: list[dict], balance: float | None, today: date) -> list[dict]:
    """Daily closing balance, from the current balance minus the bookings after each day."""
    booked = sorted((r for r in rows if not r["pending"] and r["date"] <= today), key=lambda r: r["date"])
    if balance is None or not booked:
        return []
    by_day: dict[date, float] = defaultdict(float)
    for row in booked:
        by_day[row["date"]] += row["amount"]
    series, value = [], balance
    for day in reversed(list(_days(booked[0]["date"], today))):
        series.append({"date": day, "balance": round(value, 2)})
        value -= by_day.get(day, 0.0)
    series.reverse()
    return series
