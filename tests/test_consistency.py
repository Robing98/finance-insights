"""Figures shown in more than one place must agree.

Every number here is one a user can read off two different cards. When two of them disagree, one is
wrong and the dashboard cannot be trusted, which is worse than a missing figure. These checks run
against the sample exports, so they cover the real code path rather than hand-made dictionaries.
"""
from datetime import date
from pathlib import Path

import pytest

from custom_components.finance_insights import (bank_core, business_core, dividend_core, health_core, overview_core,
                                                tr_core)

TODAY = date(2026, 9, 15)
HERE = Path(__file__).parent
IBAN = "DE12500500000123456789"
MONTHS = overview_core._months_back(TODAY, 12)  # noqa: SLF001


@pytest.fixture(scope="module")
def bank():
    rows = bank_core.classify(bank_core.merge_exports([bank_core.read_sparkasse_csv((HERE / "sparkasse_sample.csv").read_bytes())]),
                              own_ibans={IBAN}, keywords=["Trade Republic"])
    result = bank_core.analyze_bank(rows, TODAY)
    result["balance"] = 2500.0  # the sample ships no balance file, and the overview needs one
    return result


@pytest.fixture(scope="module")
def broker_rows():
    return tr_core.read_tr_csv(str(HERE / "sample.csv"))


@pytest.fixture(scope="module")
def broker(broker_rows):
    result = tr_core.analyze(broker_rows, today=TODAY)
    result["dividends"] = dividend_core.analyze_dividends(result, broker_rows, {}, {}, {}, TODAY)
    result["health"] = health_core.analyze_health(result, broker_rows, TODAY)
    return result


@pytest.fixture(scope="module")
def overview(bank, broker):
    return overview_core.build_overview([("Sparkasse", bank)], [("Trade Republic", broker)], TODAY)


def same(a, b, tol=0.02):
    assert (a or 0) == pytest.approx(b or 0, abs=tol)


#: A percentage is stored rounded to one decimal, so it can sit half a step from the exact ratio.
PERCENT = 0.06


# ---------------------------------------------------------------- bank account

def test_bank_income_adds_up_the_same_way_everywhere(bank):
    """Headline, donut, by-kind table, payer table and the monthly bars all read the same year."""
    total = bank["income_12m"]
    same(total, sum(bank["income_kinds_12m"].values()))
    same(total, sum(p[1] for p in bank["payers_12m"]))
    same(total, sum(m["income"] for m in bank["monthly"] if m["month"] in MONTHS))


def test_bank_spending_adds_up_the_same_way_everywhere(bank):
    total = bank["spending_12m"]
    same(total, sum(bank["groups_12m"].values()))
    same(total, sum(c[1] for c in bank["categories_12m"]))
    same(total, sum(m["spending"] for m in bank["monthly"] if m["month"] in MONTHS))


def test_bank_month_totals_match_their_own_breakdown(bank):
    for month in bank["monthly"]:
        same(sum(month["in"].values()), month["income"])
        same(sum(month[group] for group in bank_core.GROUP_ORDER), month["spending"])


def test_bank_saved_and_the_average_follow_from_the_totals(bank):
    same(bank["saved_12m"], bank["income_12m"] - bank["spending_12m"])
    same(bank["avg_income_12m"], bank["income_12m"] / bank["months_12m"])
    same(bank["avg_spending_12m"], bank["spending_12m"] / bank["months_12m"])
    same(bank["savings_rate_12m"], bank["saved_12m"] / bank["income_12m"] * 100, PERCENT)


# ---------------------------------------------------------------- broker account

def test_broker_net_worth_is_its_parts(broker):
    summary = broker["summary"]
    same(summary["net_worth"], summary["cash"] + summary["holdings_value"])
    same(summary["holdings_value"], sum(h["value"] or 0 for h in broker["holdings"]))
    same(100.0, sum(h["weight_pct"] for h in broker["holdings"] if h["value"]), PERCENT)


def test_broker_income_adds_up_the_same_way_everywhere(broker):
    summary = broker["summary"]
    same(summary["income"], sum(r["value"] for r in broker["income"]))
    year = str(TODAY.year)
    same(summary["income_ytd"], sum(broker["income_by_year_kind"][year].values()))
    since = TODAY.replace(year=TODAY.year - 1).isoformat()
    same(sum(broker["income_kinds_12m"].values()), sum(r["value"] for r in broker["income"] if r["date"] > since))


def test_broker_spending_adds_up_the_same_way_everywhere(broker):
    summary = broker["summary"]
    same(summary["spending"], sum(x["value"] for x in broker["spending"]))
    same(summary["spending"], sum(m["spending"] for m in broker["monthly"]))
    same(summary["spending"], sum(c["value"] for c in broker["spending_by_category"]))
    same(summary["spending_ytd"], sum(x["value"] for x in broker["spending"] if x["year"] == TODAY.year))


def test_dividend_figures_follow_from_the_payments(broker):
    dividends = broker["dividends"]
    same(dividends["annual_income"], sum(s["annual_income"] or 0 for s in dividends["stocks"]))
    same(dividends["received_total"], sum(r["value"] for r in broker["income"] if r["kind"] == "Dividends"))
    same(sum(c["amount"] for c in dividends["calendar"]), sum(c["amount"] for c in dividends["calendar"]))


def test_the_checks_measure_what_the_holdings_say(broker):
    health, summary = broker["health"], broker["summary"]
    same(sum(health["allocation"].values()), summary["holdings_value"])
    assert health["largest_pct"] == pytest.approx(max(h["weight_pct"] for h in broker["holdings"]), abs=0.05)
    assert health["positions"] == summary["positions"]


# ---------------------------------------------------------------- household

def test_overview_net_worth_is_its_parts(overview, bank, broker):
    summary = broker["summary"]
    same(overview["net_worth"], bank["balance"] + summary["cash"] + summary["holdings_value"])
    same(sum(overview["split"].values()), overview["net_worth"])
    same(overview["liquid"] + overview["invested"], overview["net_worth"])


def test_overview_windows_are_the_sum_of_the_accounts(overview, bank, broker):
    summary = broker["summary"]
    same(overview["income_30d"], bank["income_30d"] + summary["income_30d"])
    same(overview["spending_30d"], bank["spending_30d"] + summary["spending_30d"])
    same(overview["income_prev_30d"], bank["income_prev_30d"] + summary["income_prev_30d"])
    same(overview["to_depot_12m"], sum(m["to_depot"] for m in overview["monthly"]))


def test_overview_saved_follows_from_its_own_months(overview):
    income = sum(m["income"] for m in overview["monthly"])
    spending = sum(m["spending"] for m in overview["monthly"])
    same(overview["saved_12m"], income - spending)
    same(overview["savings_rate_12m"], (income - spending) / income * 100, PERCENT)


def test_the_cash_flow_chart_agrees_with_the_figures_beside_it(overview):
    """The chart and the Saved figure sit on the same tab. This is the check that caught 0.14.0
    counting a transfer to the depot as spending and inventing a deficit of 1.945 EUR."""
    flow = overview["cash_flow"]["periods"]["12"]
    sources = {i["name"]: i["value"] for i in flow["sources"]}
    uses = {i["name"]: i["value"] for i in flow["uses"]}
    surplus = uses.get("Invested", 0) + uses.get("Left over", 0) - sources.get("From savings", 0)
    same(surplus, overview["saved_12m"])
    same(flow["total"] - sources.get("From savings", 0), sum(m["income"] for m in overview["monthly"]))
    spent = sum(v for k, v in uses.items() if k not in ("Invested", "Left over"))
    same(spent, sum(m["spending"] for m in overview["monthly"]))


def test_every_window_of_the_chart_balances(overview):
    for period in overview["cash_flow"]["periods"].values():
        same(sum(i["value"] for i in period["sources"]), sum(i["value"] for i in period["uses"]))


# ---------------------------------------------------------------- business account

def test_business_net_and_vat_add_up_to_the_gross(bank):
    rows = [{"date": date.fromisoformat(m["month"] + "-15"), "month": m["month"], "year": int(m["month"][:4]),
             "amount": 1190.0, "kind": "income", "merchant": "Kunde", "purpose": "RECHNUNG", "booking_text": "",
             "counterparty": "", "pending": False, "category": None} for m in bank["monthly"][-3:]]
    rules = business_core.read_vat_rules("pattern,category,vat\nRECHNUNG,Revenue,19\n")
    result = business_core.analyze_business(rows, TODAY, rules=rules, default_rate=19)
    year = result["year"]
    same(year["revenue_net"] + year["vat_collected"], 3 * 1190.0)
    for month in result["months"]:
        same(month["revenue_net"] + month["vat_collected"], month["revenue_gross"])
