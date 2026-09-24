"""Combine bank and broker results into one household view."""
from __future__ import annotations

from collections import defaultdict
from datetime import date

#: Card spending on a broker account is not grouped the way bank spending is, so it stays one entry.
BROKER_SPENDING = "Card spending"
INVESTED = "Invested"
LEFT_OVER = "Left over"
#: A year in which more went out than came in was paid for from what was there before.
FROM_SAVINGS = "From savings"


def _months_back(today: date, n: int) -> list[str]:
    y, m, out = today.year, today.month, []
    for _ in range(n):
        out.append(f"{y}-{m:02d}")
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return out[::-1]


def cash_flow(banks: list[tuple[str, dict]], brokers: list[tuple[str, dict]], months: list[str],
              invested: float) -> dict:
    """Where the money came from and where it went over the last twelve months.

    Both sides add up to the same total, so the picture balances: everything that came in either
    went somewhere or is left over. A year that spent more than it earned took the difference from
    what was there before, which is shown as an extra source rather than as a negative flow.
    """
    sources: dict[str, float] = defaultdict(float)
    uses: dict[str, float] = defaultdict(float)
    for _, res in banks + brokers:
        for kind, value in (res.get("income_kinds_12m") or {}).items():
            sources[kind] += value
    for _, res in banks:
        for group, value in (res.get("groups_12m") or {}).items():
            uses[group] += value
    for _, res in brokers:
        uses[BROKER_SPENDING] += sum(m["spending"] for m in res["monthly"] if m["month"] in months)

    income = round(sum(sources.values()), 2)
    spent = round(sum(uses.values()), 2)
    rest = round(income - spent - invested, 2)
    if invested > 0:
        uses[INVESTED] = invested
    if rest >= 0:
        uses[LEFT_OVER] = rest
    else:
        sources[FROM_SAVINGS] = -rest

    def listed(values: dict[str, float]) -> list[dict]:
        return [{"name": k, "value": round(v, 2)} for k, v in sorted(values.items(), key=lambda kv: -kv[1])
                if round(v, 2) > 0]

    return dict(sources=listed(sources), uses=listed(uses),
                total=round(sum(v for v in sources.values() if v > 0), 2), months=len(months))


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
        cash_flow=cash_flow(banks, brokers, months, round(sum(m["to_depot"] for m in monthly), 2)),
        missing_balances=[n for n, r in banks if r["balance"] is None],
    )
