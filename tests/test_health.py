"""Descriptive checks on the shape of a portfolio."""
from datetime import date

from custom_components.finance_insights import health_core

TODAY = date(2026, 9, 15)


def _holding(name: str, value: float | None, weight: float, cost: float = 0.0, source: str = "live"):
    return {"symbol": f"X{name}", "name": name, "asset_class": "STOCK", "value": value, "weight_pct": weight,
            "cost": cost or (value or 0.0), "price_source": source}


def _analyze(holdings, summary=None, dividends=None, rows=None):
    result = {"holdings": holdings, "summary": summary or {"cash": 0.0, "holdings_value": sum(h["value"] or 0 for h in holdings)},
              "dividends": dividends or {}}
    return health_core.analyze_health(result, rows or [], TODAY)


def _check(out, key):
    return next(c for c in out["checks"] if c["key"] == key)


def _even(n: int, total: float = 100.0):
    return [_holding(f"P{i}", total / n, 100 / n) for i in range(n)]


def test_an_evenly_spread_portfolio_passes():
    out = _analyze(_even(10))
    assert _check(out, "concentration")["level"] == health_core.OK
    assert out["watch"] == 0 and out["largest_pct"] == 10.0


def test_one_position_taking_over_is_measured_and_named():
    holdings = [_holding("Big", 400.0, 40.0), *(_holding(f"P{i}", 100.0, 10.0) for i in range(6))]
    out = _analyze(holdings)
    check = _check(out, "concentration")
    assert check["level"] == health_core.WATCH and check["value"] == 40.0 and check["name"] == "Big"
    assert check["unit"] == "%" and check["limit"] == 15.0
    # The top five hold 80 percent here, so that is a second watch.
    assert {c["key"] for c in out["checks"] if c["level"] == health_core.WATCH} == {"concentration", "top5"}


def test_the_top_five_are_only_measured_once_there_are_more():
    assert "top5_pct" not in _analyze(_even(5))
    assert _analyze(_even(6))["top5_pct"] == 83.3


def test_cash_is_measured_against_the_whole_account():
    out = _analyze(_even(4, 600.0), summary={"cash": 400.0, "holdings_value": 600.0})
    assert _check(out, "cash")["value"] == 40.0 and _check(out, "cash")["level"] == health_core.WATCH


def test_an_account_without_cash_is_not_checked_for_it():
    out = _analyze(_even(4), summary={"cash": 0.0, "holdings_value": 100.0})
    assert not [c for c in out["checks"] if c["key"] == "cash"]


def test_a_position_without_a_price_is_a_watch_because_every_total_misses_it():
    out = _analyze([_holding("A", 900.0, 100.0), _holding("Unpriced", None, 0.0, cost=250.0, source="no price")])
    check = _check(out, "unpriced")
    assert check["level"] == health_core.WATCH and check["value"] == 1 and check["cost"] == 250.0
    assert check["names"] == ["Unpriced"] and check["unit"] is None


def test_a_price_from_an_old_trade_is_reported_as_stale():
    fresh = _holding("Fresh", 100.0, 50.0, source="last trade 2026-09-10")
    old = _holding("Old", 100.0, 50.0, source="last trade 2026-01-02")
    out = _analyze([fresh, old])
    assert _check(out, "stale_prices")["names"] == ["Old"]


def test_dividend_income_leaning_on_one_payer_is_measured():
    dividends = {"stocks": [{"name": "Payer", "annual_income": 400.0, "currency": "USD"},
                            {"name": "Other", "annual_income": 100.0, "currency": "EUR"}]}
    out = _analyze(_even(4), dividends=dividends)
    assert _check(out, "dividend_concentration")["value"] == 80.0
    assert _check(out, "foreign_dividends")["value"] == 80.0
    assert out["by_currency"] == {"USD": 400.0, "EUR": 100.0}


def test_order_fees_are_measured_against_what_was_bought():
    rows = [{"date": "2026-08-01", "bucket": "trade", "shares": 1.0, "amount": -500.0, "fee": -1.0},
            {"date": "2026-08-02", "bucket": "trade", "shares": 1.0, "amount": -500.0, "fee": -1.0},
            {"date": "2024-01-02", "bucket": "trade", "shares": 1.0, "amount": -500.0, "fee": -50.0}]
    out = _analyze(_even(4), rows=rows)
    check = _check(out, "fees")
    assert check["value"] == 0.2 and check["amount"] == 2.0 and check["trades"] == 2  # the old trade is outside the year


def test_watches_come_first_so_the_card_reads_top_down():
    holdings = [_holding("Big", 400.0, 40.0), _holding("Unpriced", None, 0.0, cost=10.0),
                *(_holding(f"P{i}", 100.0, 10.0) for i in range(6))]
    out = _analyze(holdings, summary={"cash": 20.0, "holdings_value": 1000.0})
    assert [c["level"] for c in out["checks"]][:2] == [health_core.WATCH, health_core.WATCH]
    assert out["checks"][-1]["level"] == health_core.OK


def test_an_empty_account_reports_nothing_to_check():
    assert _analyze([]) == {"checks": [], "watch": 0, "notes": 0, "positions": 0}
