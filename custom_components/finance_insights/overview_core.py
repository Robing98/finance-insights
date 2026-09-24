"""Combine bank and broker results into one household view."""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from . import bank_core, tr_core

INVESTED = "Invested"
LEFT_OVER = "Left over"
#: A period in which more went out than came in was paid for from what was there before.
FROM_SAVINGS = "From savings"
#: The broker groups card spending by merchant type, the bank by its own categories. These names
#: mean the same thing, so the household view shows one set instead of two vocabularies.
BROKER_GROUPS = {"Home": "Housing", "Subscriptions": "Subscriptions and leisure",
                 "Transport and travel": "Mobility and travel"}
#: Windows the cash flow chart offers, in months.
PERIODS = (3, 6, 12)


def broker_group(category: str) -> str:
    group = tr_core.spending_group(category)
    return BROKER_GROUPS.get(group, group)


def _months_back(today: date, n: int) -> list[str]:
    y, m, out = today.year, today.month, []
    for _ in range(n):
        out.append(f"{y}-{m:02d}")
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return out[::-1]


def _flow_months(banks: list[tuple[str, dict]], brokers: list[tuple[str, dict]],
                 months: list[str]) -> dict[str, dict]:
    """Per month: what came in by kind, what went out by group, and what moved to a depot.

    Keeping it per month is what lets the chart answer the same question over three months as over
    twelve, which matters when an account is younger than the window.
    """
    per = {m: {"sources": defaultdict(float), "uses": defaultdict(float), "invested": 0.0} for m in months}
    for _, res in banks:
        for entry in res.get("monthly") or []:
            slot = per.get(entry["month"])
            if slot is None:
                continue
            for kind, value in (entry.get("in") or {}).items():
                slot["sources"][kind] += value
            for group in bank_core.GROUP_ORDER:
                if entry.get(group):
                    slot["uses"][group] += entry[group]
            slot["invested"] += entry.get("to_depot") or 0.0
    for _, res in brokers:
        for row in res.get("income") or []:
            slot = per.get(str(row["date"])[:7])
            if slot is not None:
                slot["sources"][row["kind"]] += row["value"]
        for row in res.get("spending") or []:
            slot = per.get(row["month"])
            if slot is not None:
                slot["uses"][broker_group(row["category"])] += row["value"]
    return per


def _listed(values: dict[str, float]) -> list[dict]:
    return [{"name": k, "value": round(v, 2)} for k, v in sorted(values.items(), key=lambda kv: -kv[1])
            if round(v, 2) > 0]


def _aggregate(per: dict[str, dict], window: list[str]) -> dict:
    """Both sides add up to the same total, so the picture balances: everything that came in was
    either spent or is left over.

    What moved from a bank account to a depot is a transfer between the owner's own accounts, not
    spending: the money it paid for is already counted where it was actually spent. It never counts
    as a use of its own, it only splits the surplus, to show how much of what was left over went to
    the depot rather than staying on the account. A period that spent more than it earned took the
    difference from what was there before, shown as an extra source rather than a negative flow.
    """
    sources: dict[str, float] = defaultdict(float)
    uses: dict[str, float] = defaultdict(float)
    invested = 0.0
    for month in window:
        slot = per[month]
        for kind, value in slot["sources"].items():
            sources[kind] += value
        for group, value in slot["uses"].items():
            uses[group] += value
        invested += slot["invested"]

    income = round(sum(sources.values()), 2)
    rest = round(income - round(sum(uses.values()), 2), 2)
    if rest < 0:
        sources[FROM_SAVINGS] = -rest
    else:
        # More can go to the depot than was earned in the window, paid for from what was there
        # before. Only the part this window's surplus covers belongs in the picture.
        to_depot = min(max(invested, 0.0), rest)
        uses[INVESTED] = to_depot
        uses[LEFT_OVER] = round(rest - to_depot, 2)
    return dict(sources=_listed(sources), uses=_listed(uses),
                total=round(sum(v for v in sources.values() if v > 0), 2), months=len(window))


def cash_flow(banks: list[tuple[str, dict]], brokers: list[tuple[str, dict]], months: list[str]) -> dict:
    """The longest window, plus every shorter one the chart offers."""
    per = _flow_months(banks, brokers, months)
    periods = {str(n): _aggregate(per, months[-n:]) for n in PERIODS if n <= len(months)}
    longest = max(int(n) for n in periods) if periods else 0
    return {**(periods.get(str(longest)) or _aggregate(per, months)), "periods": periods}


def build_overview(banks: list[tuple[str, dict]], brokers: list[tuple[str, dict]], today: date) -> dict:
    """banks: [(name, analyze_bank result)], brokers: [(name, tr_core.analyze result)].
    Transfers between the accounts are already excluded from bank income and spending."""
    months = _months_back(today, 12)
    bank_month = {}
    for _, res in banks:
        for m in res["monthly"]:
            b = bank_month.setdefault(m["month"], {"income": 0.0, "spending": 0.0, "to_depot": 0.0})
            b["income"] += m["income"]
            b["spending"] += m["spending"]
            b["to_depot"] += m["to_depot"]
    broker_month = {}
    for _, res in brokers:
        for m in res["monthly"]:
            b = broker_month.setdefault(m["month"], {"income": 0.0, "spending": 0.0})
            b["income"] += m["income"]
            b["spending"] += m["spending"]

    monthly = []
    for m in months:
        bk, br = bank_month.get(m, {}), broker_month.get(m, {})
        inc = bk.get("income", 0.0) + br.get("income", 0.0)
        sp = bk.get("spending", 0.0) + br.get("spending", 0.0)
        monthly.append({"month": m, "income": round(inc, 2), "spending": round(sp, 2), "saved": round(inc - sp, 2),
                        "to_depot": round(bk.get("to_depot", 0.0), 2)})

    # Rolling windows come from the accounts, because a month total cannot be cut to 30 days.
    def rolling(field: str) -> float:
        return round(sum(r.get(field, 0.0) for _, r in banks)
                     + sum(r["summary"].get(field, 0.0) for _, r in brokers), 2)

    bank_balance = sum(r["balance"] for _, r in banks if r["balance"] is not None)
    broker_cash = sum(r["summary"]["cash"] for _, r in brokers)
    invested = sum(r["summary"]["holdings_value"] for _, r in brokers)
    inc12 = sum(m["income"] for m in monthly)
    sp12 = sum(m["spending"] for m in monthly)
    # Each account is averaged over the months its data covers, then summed.
    def broker_avg(field: str) -> float:
        total = 0.0
        for _, res in brokers:
            covered = res["summary"].get("months_12m") or 12.0
            total += sum(m[field] for m in res["monthly"] if m["month"] in months) / covered
        return total

    avg_income = round(sum(r["avg_income_12m"] for _, r in banks) + broker_avg("income"), 2)
    avg_spending = round(sum(r["avg_spending_12m"] for _, r in banks) + broker_avg("spending"), 2)
    accounts = [{"name": n, "type": "bank", "balance": r["balance"], "balance_source": r["balance_source"]} for n, r in banks]
    accounts += [{"name": n, "type": "broker", "cash": r["summary"]["cash"], "holdings": r["summary"]["holdings_value"]}
                 for n, r in brokers]
    return dict(
        net_worth=round(bank_balance + broker_cash + invested, 2),
        liquid=round(bank_balance + broker_cash, 2), invested=round(invested, 2),
        split={"Bank accounts": round(bank_balance, 2), "Broker cash": round(broker_cash, 2), "Investments": round(invested, 2)},
        income_month=monthly[-1]["income"], spending_month=monthly[-1]["spending"],
        income_30d=rolling("income_30d"), spending_30d=rolling("spending_30d"),
        income_prev_30d=rolling("income_prev_30d"), spending_prev_30d=rolling("spending_prev_30d"),
        avg_income_12m=avg_income, avg_spending_12m=avg_spending,
        saved_12m=round(inc12 - sp12, 2),
        savings_rate_12m=round((inc12 - sp12) / inc12 * 100, 1) if inc12 > 0 else None,
        to_depot_12m=round(sum(m["to_depot"] for m in monthly), 2),
        monthly=monthly, accounts=accounts,
        cash_flow=cash_flow(banks, brokers, months),
        missing_balances=[n for n, r in banks if r["balance"] is None],
    )
