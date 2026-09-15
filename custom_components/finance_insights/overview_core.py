"""Combine bank and broker results into one household view."""
from __future__ import annotations

from datetime import date


def _months_back(today: date, n: int) -> list[str]:
    y, m, out = today.year, today.month, []
    for _ in range(n):
        out.append(f"{y}-{m:02d}")
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return out[::-1]


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

    bank_balance = sum(r["balance"] for _, r in banks if r["balance"] is not None)
    broker_cash = sum(r["summary"]["cash"] for _, r in brokers)
    invested = sum(r["summary"]["holdings_value"] for _, r in brokers)
    inc12 = sum(m["income"] for m in monthly)
    sp12 = sum(m["spending"] for m in monthly)
    accounts = [{"name": n, "type": "bank", "balance": r["balance"], "balance_source": r["balance_source"]} for n, r in banks]
    accounts += [{"name": n, "type": "broker", "cash": r["summary"]["cash"], "holdings": r["summary"]["holdings_value"]}
                 for n, r in brokers]
    return dict(
        net_worth=round(bank_balance + broker_cash + invested, 2),
        liquid=round(bank_balance + broker_cash, 2), invested=round(invested, 2),
        split={"Bank accounts": round(bank_balance, 2), "Broker cash": round(broker_cash, 2), "Investments": round(invested, 2)},
        income_month=monthly[-1]["income"], spending_month=monthly[-1]["spending"],
        avg_income_12m=round(inc12 / 12, 2), avg_spending_12m=round(sp12 / 12, 2),
        savings_rate_12m=round((inc12 - sp12) / inc12 * 100, 1) if inc12 > 0 else None,
        to_depot_12m=round(sum(m["to_depot"] for m in monthly), 2),
        monthly=monthly, accounts=accounts,
        missing_balances=[n for n, r in banks if r["balance"] is None],
    )
