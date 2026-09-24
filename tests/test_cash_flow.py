"""Where the money came from and where it went, over twelve months."""
from datetime import date

import pytest

from custom_components.finance_insights import overview_core

TODAY = date(2026, 9, 15)


def _bank(income=None, groups=None, to_depot=0.0, balance=1000.0):
    months = overview_core._months_back(TODAY, 12)  # noqa: SLF001
    monthly = [{"month": m, "income": 0.0, "spending": 0.0, "to_depot": to_depot / 12} for m in months]
    return ("Sparkasse", {
        "income_kinds_12m": income or {}, "groups_12m": groups or {}, "monthly": monthly,
        "balance": balance, "balance_source": "test", "avg_income_12m": 0.0, "avg_spending_12m": 0.0,
        "income_30d": 0.0, "income_prev_30d": 0.0, "spending_30d": 0.0, "spending_prev_30d": 0.0,
    })


def _broker(income=None, spending=0.0):
    months = overview_core._months_back(TODAY, 12)  # noqa: SLF001
    return ("Trade Republic", {
        "income_kinds_12m": income or {},
        "monthly": [{"month": m, "income": 0.0, "spending": spending / 12} for m in months],
        "summary": {"cash": 0.0, "holdings_value": 0.0, "months_12m": 12.0, "income_30d": 0.0,
                    "spending_30d": 0.0, "income_prev_30d": 0.0, "spending_prev_30d": 0.0},
    })


def _flow(banks, brokers, invested=0.0):
    months = overview_core._months_back(TODAY, 12)  # noqa: SLF001
    return overview_core.cash_flow(banks, brokers, months, invested)


def _by_name(side):
    return {item["name"]: item["value"] for item in side}


def test_both_sides_carry_the_same_total():
    """The picture only means anything if nothing appears or disappears in the middle."""
    flow = _flow([_bank({"Salary": 3000.0}, {"Housing": 1000.0, "Food and drink": 400.0})],
                 [_broker({"Dividends": 120.0})], invested=500.0)
    assert sum(i["value"] for i in flow["sources"]) == pytest.approx(sum(i["value"] for i in flow["uses"]))
    assert flow["total"] == pytest.approx(3120.0)


def test_what_is_not_spent_or_invested_is_left_over():
    flow = _flow([_bank({"Salary": 3000.0}, {"Housing": 1000.0})], [], invested=500.0)
    uses = _by_name(flow["uses"])
    assert uses["Housing"] == 1000.0 and uses["Invested"] == 500.0 and uses["Left over"] == 1500.0


def test_a_year_that_spent_more_than_it_earned_took_it_from_savings():
    """A negative flow cannot be drawn, so the difference becomes a source instead."""
    flow = _flow([_bank({"Salary": 1000.0}, {"Housing": 1400.0})], [])
    assert _by_name(flow["sources"])["From savings"] == 400.0
    assert "Left over" not in _by_name(flow["uses"])
    assert sum(i["value"] for i in flow["sources"]) == pytest.approx(sum(i["value"] for i in flow["uses"]))


def test_income_of_every_account_ends_up_on_the_left():
    flow = _flow([_bank({"Salary": 2000.0, "Interest": 10.0})], [_broker({"Dividends": 50.0, "Saveback": 5.0})])
    assert set(_by_name(flow["sources"])) == {"Salary", "Interest", "Dividends", "Saveback"}


def test_card_spending_on_a_broker_account_is_one_entry():
    """Broker spending is not grouped the way bank spending is, so it is not mixed into those groups."""
    flow = _flow([_bank({"Salary": 2000.0}, {"Housing": 500.0})], [_broker(spending=240.0)])
    assert _by_name(flow["uses"])["Card spending"] == pytest.approx(240.0)


def test_an_empty_household_produces_nothing_to_draw():
    flow = _flow([_bank()], [])
    assert flow["sources"] == [] and flow["uses"] == [] and flow["total"] == 0.0


def test_entries_worth_nothing_are_left_out():
    flow = _flow([_bank({"Salary": 100.0, "Interest": 0.0}, {"Housing": 100.0, "Shopping": 0.0})], [])
    assert [i["name"] for i in flow["sources"]] == ["Salary"]
    assert [i["name"] for i in flow["uses"]] == ["Housing"]


def test_the_largest_flow_comes_first():
    flow = _flow([_bank({"Interest": 10.0, "Salary": 3000.0}, {"Food and drink": 400.0, "Housing": 1000.0})], [])
    assert [i["name"] for i in flow["sources"]] == ["Salary", "Interest"]
    assert [i["name"] for i in flow["uses"]][:2] == ["Left over", "Housing"]
