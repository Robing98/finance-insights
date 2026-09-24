"""Where the money came from and where it went, over a window the chart can change."""
from datetime import date

import pytest

from custom_components.finance_insights import overview_core

TODAY = date(2026, 9, 15)
MONTHS = overview_core._months_back(TODAY, 12)  # noqa: SLF001


def _bank(income=None, groups=None, to_depot=0.0, months=1):
    """A bank account whose figures fall into the most recent `months` months, split evenly."""
    recent = set(MONTHS[-months:])
    monthly = []
    for month in MONTHS:
        entry = {"month": month, "income": 0.0, "spending": 0.0, "saved": 0.0, "to_depot": 0.0, "in": {}}
        if month in recent:
            entry["in"] = {k: v / months for k, v in (income or {}).items()}
            entry["income"] = round(sum(entry["in"].values()), 2)
            for group, value in (groups or {}).items():
                entry[group] = value / months
            entry["spending"] = round(sum((groups or {}).values()) / months, 2)
            entry["to_depot"] = to_depot / months
        monthly.append(entry)
    return ("Sparkasse", {"monthly": monthly})


def _broker(income=None, spending=None, month=None):
    """A broker account with dividend-style income and card spending by merchant category."""
    month = month or MONTHS[-1]
    return ("Trade Republic", {
        "income": [{"date": f"{month}-15", "kind": kind, "name": kind, "value": value, "tax": 0.0}
                   for kind, value in (income or {}).items()],
        "spending": [{"date": f"{month}-15", "month": month, "year": int(month[:4]), "value": value,
                      "merchant": "Shop", "category": category}
                     for category, value in (spending or {}).items()],
    })


def _flow(banks, brokers, months=None):
    return overview_core.cash_flow(banks, brokers, months or MONTHS)


def _by_name(side):
    return {item["name"]: item["value"] for item in side}


def test_both_sides_carry_the_same_total():
    """The picture only means anything if nothing appears or disappears in the middle."""
    flow = _flow([_bank({"Salary": 3000.0}, {"Housing": 1000.0, "Food and drink": 400.0}, to_depot=500.0)],
                 [_broker({"Dividends": 120.0})])
    assert sum(i["value"] for i in flow["sources"]) == pytest.approx(sum(i["value"] for i in flow["uses"]))
    assert flow["total"] == pytest.approx(3120.0)


def test_what_is_not_spent_or_invested_is_left_over():
    flow = _flow([_bank({"Salary": 3000.0}, {"Housing": 1000.0}, to_depot=500.0)], [])
    uses = _by_name(flow["uses"])
    assert uses["Housing"] == 1000.0 and uses["Invested"] == 500.0 and uses["Left over"] == 1500.0


def test_a_transfer_to_the_depot_is_not_spending():
    """It is a move between your own pockets. Counting it, and then counting what it paid for,
    charges the same euro twice and invents a raid on your savings that never happened."""
    flow = _flow([_bank({"Salary": 1000.0}, {"Housing": 900.0}, to_depot=500.0)], [])
    assert "From savings" not in _by_name(flow["sources"])
    uses = _by_name(flow["uses"])
    assert uses["Housing"] == 900.0
    # Only the part of the transfer that this window's surplus covers belongs in the picture.
    assert uses["Invested"] == 100.0
    assert sum(i["value"] for i in flow["uses"]) == pytest.approx(1000.0)


def test_the_chart_agrees_with_what_the_account_says_was_saved():
    """The overview shows both. If they disagree, one of them is wrong."""
    income, spending, to_depot = 3853.0, 7412.0, 1945.0
    flow = _flow([_bank({"Salary": income}, {"Housing": spending}, to_depot=to_depot)], [])
    assert _by_name(flow["sources"])["From savings"] == pytest.approx(spending - income)
    assert "Invested" not in _by_name(flow["uses"])


def test_a_surplus_smaller_than_the_transfer_is_not_a_deficit():
    flow = _flow([_bank({"Salary": 2000.0}, {"Housing": 500.0}, to_depot=5000.0)], [])
    assert "From savings" not in _by_name(flow["sources"])
    assert _by_name(flow["uses"])["Invested"] == 1500.0


def test_a_period_that_spent_more_than_it_earned_took_it_from_savings():
    """A negative flow cannot be drawn, so the difference becomes a source instead."""
    flow = _flow([_bank({"Salary": 1000.0}, {"Housing": 1400.0})], [])
    assert _by_name(flow["sources"])["From savings"] == 400.0
    assert "Left over" not in _by_name(flow["uses"])
    assert sum(i["value"] for i in flow["sources"]) == pytest.approx(sum(i["value"] for i in flow["uses"]))


def test_income_of_every_account_ends_up_on_the_left():
    flow = _flow([_bank({"Salary": 2000.0, "Interest": 10.0})], [_broker({"Dividends": 50.0, "Saveback": 5.0})])
    assert set(_by_name(flow["sources"])) >= {"Salary", "Interest", "Dividends", "Saveback"}


def test_card_spending_is_grouped_like_bank_spending():
    """Two vocabularies for the same thing would split one category across two nodes."""
    flow = _flow([_bank({"Salary": 2000.0}, {"Food and drink": 100.0})],
                 [_broker(spending={"Groceries": 50.0, "Streaming and media": 20.0, "Transport": 30.0})])
    uses = _by_name(flow["uses"])
    assert uses["Food and drink"] == 150.0          # the bank's 100 and the broker's groceries
    assert uses["Subscriptions and leisure"] == 20.0  # the broker calls this "Subscriptions"
    assert uses["Mobility and travel"] == 30.0        # and this "Transport and travel"
    assert "Card spending" not in uses


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


# ---------------------------------------------------------------- windows

def test_every_window_is_offered_and_balances():
    flow = _flow([_bank({"Salary": 12000.0}, {"Housing": 6000.0}, months=12)], [])
    assert sorted(flow["periods"], key=int) == ["3", "6", "12"]
    for period in flow["periods"].values():
        assert sum(i["value"] for i in period["sources"]) == pytest.approx(sum(i["value"] for i in period["uses"]))


def test_a_shorter_window_counts_only_its_own_months():
    """An account younger than a year drowns in a twelve-month window; three months is the point."""
    flow = _flow([_bank({"Salary": 3000.0}, {"Housing": 600.0}, months=3)], [])
    assert flow["periods"]["3"]["total"] == pytest.approx(3000.0)
    assert flow["periods"]["12"]["total"] == pytest.approx(3000.0)
    assert flow["periods"]["3"]["months"] == 3 and flow["periods"]["12"]["months"] == 12


def test_a_window_can_turn_a_deficit_into_a_surplus():
    """Twelve months of spending against three months of salary is not the same question."""
    bank = _bank({"Salary": 3000.0}, {"Housing": 600.0}, months=3)
    old = _broker(spending={"Groceries": 4000.0}, month=MONTHS[0])
    flow = _flow([bank], [old])
    assert _by_name(flow["periods"]["12"]["sources"])["From savings"] == pytest.approx(1600.0)
    assert _by_name(flow["periods"]["3"]["uses"])["Left over"] == pytest.approx(2400.0)


def test_the_longest_window_is_what_the_card_shows_by_default():
    flow = _flow([_bank({"Salary": 1200.0}, {"Housing": 600.0}, months=12)], [])
    assert flow["sources"] == flow["periods"]["12"]["sources"]
    assert flow["months"] == 12
