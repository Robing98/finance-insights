"""Events on the positions you hold."""
from datetime import date

from custom_components.finance_insights import watch_core
from custom_components.finance_insights.market_data import DividendEvent

TODAY = date(2026, 9, 15)
ISIN = "US0378331005"


def _event(day: str, amount: float, currency="USD"):
    return DividendEvent(date.fromisoformat(day), amount, currency, source="test")


def _result(holdings=None, stocks=None, upcoming=None):
    return {
        "holdings": holdings if holdings is not None else [{"symbol": ISIN, "name": "Apple", "value": 1000.0}],
        "dividends": {"stocks": stocks or [], "upcoming": upcoming or []},
    }


def _row(day: str, kind="SWAP", symbol=ISIN, name="Apple", rid=None):
    return {"date": day, "datetime": f"{day}T10:00:00", "type": kind, "bucket": "corporate", "symbol": symbol,
            "name": name, "shares": 1.0, "amount": None, "id": rid}


def _run(result, rows, events, state, today=TODAY):
    return watch_core.analyze_watch(result, rows, events, state, today)


def test_the_first_run_records_and_reports_nothing():
    """Connecting an account must not produce a feed full of old news."""
    out = _run(_result(), [_row("2026-09-10")], {ISIN: [_event("2026-08-08", 0.25)]}, None)
    assert out["new"] == [] and out["view"]["items"] == []
    assert out["state"]["dividends"][ISIN] == {"2026-08-08": 0.25}
    assert out["state"]["rows"]  # the corporate action is recorded, so it never fires later


def test_a_smaller_payment_is_reported_as_a_cut():
    state = _run(_result(), [], {ISIN: [_event("2026-06-08", 0.25)]}, None)["state"]
    events = {ISIN: [_event("2026-06-08", 0.25), _event("2026-09-08", 0.20)]}
    out = _run(_result(), [], events, state)
    item = out["new"][0]
    assert item["kind"] == watch_core.KIND_CUT
    assert item["change_pct"] == -20.0 and item["previous"] == 0.25 and item["amount"] == 0.2
    assert out["view"]["changes"] == 1


def test_a_larger_payment_is_reported_as_a_raise():
    state = _run(_result(), [], {ISIN: [_event("2026-06-08", 0.25)]}, None)["state"]
    out = _run(_result(), [], {ISIN: [_event("2026-06-08", 0.25), _event("2026-09-08", 0.30)]}, state)
    assert out["new"][0]["kind"] == watch_core.KIND_RAISED and out["new"][0]["change_pct"] == 20.0


def test_an_unchanged_payment_is_only_an_announcement():
    """Rounding and fractions of a cent are not a dividend change."""
    state = _run(_result(), [], {ISIN: [_event("2026-06-08", 0.25)]}, None)["state"]
    out = _run(_result(), [], {ISIN: [_event("2026-06-08", 0.25), _event("2026-09-08", 0.2501)]}, state)
    assert out["new"][0]["kind"] == watch_core.KIND_ANNOUNCED
    assert out["view"]["changes"] == 0 and out["view"]["count"] == 1


def test_a_currency_change_is_not_read_as_a_cut():
    """A provider that switches the reporting currency would otherwise look like a 20 percent cut."""
    state = _run(_result(), [], {ISIN: [_event("2026-06-08", 1.0, "USD")]}, None)["state"]
    out = _run(_result(), [], {ISIN: [_event("2026-06-08", 1.0, "USD"), _event("2026-09-08", 0.85, "EUR")]}, state)
    assert out["new"][0]["kind"] == watch_core.KIND_ANNOUNCED and out["new"][0]["change_pct"] is None


def test_history_the_provider_only_now_returns_is_not_news():
    """Switching to a provider with more history must not fire years of old payments."""
    state = _run(_result(), [], {ISIN: [_event("2026-09-08", 0.25)]}, None)["state"]
    older = [_event(f"202{y}-09-08", 0.20) for y in range(0, 5)]
    out = _run(_result(), [], {ISIN: [*older, _event("2026-09-08", 0.25)]}, state)
    assert out["new"] == []
    assert len(out["state"]["dividends"][ISIN]) == 6  # recorded, just not announced


def test_a_position_bought_today_records_its_dividends_first():
    out = _run(_result(), [], {ISIN: [_event("2026-09-08", 0.25)]}, {"version": 1, "dividends": {}, "rows": ["x"]})
    assert out["new"] == [] and out["state"]["dividends"][ISIN]


def test_a_corporate_action_is_reported_once():
    state = _run(_result(), [], {}, None)["state"]
    out = _run(_result(), [_row("2026-09-12", "SPLIT", rid="tx1")], {}, state)
    assert [i["kind"] for i in out["new"]] == [watch_core.KIND_SPLIT]
    assert out["new"][0]["booking"] == "SPLIT"
    again = _run(_result(), [_row("2026-09-12", "SPLIT", rid="tx1")], {}, out["state"])
    assert again["new"] == [] and len(again["view"]["items"]) == 1


def test_a_booking_without_an_id_is_still_recognized():
    rows = [_row("2026-09-12", "SPIN_OFF")]
    state = _run(_result(), rows, {}, None)["state"]
    assert _run(_result(), rows, {}, state)["new"] == []


def test_a_missed_payment_is_reported_as_late_not_as_a_cut():
    # Quarterly payer, last ex date in April: by mid-September the usual gap has passed one and a half times.
    stocks = [{"isin": ISIN, "name": "Apple", "held": True, "last_ex_date": "2026-04-01", "gap_days": 91}]
    state = _run(_result(stocks=stocks), [], {ISIN: [_event("2026-04-01", 0.25)]}, None)["state"]
    out = _run(_result(stocks=stocks), [], {ISIN: [_event("2026-04-01", 0.25)]}, state)
    assert [i["kind"] for i in out["new"]] == [watch_core.KIND_LATE]
    assert out["new"][0]["gap_days"] == 91


def test_a_payment_still_within_its_rhythm_is_not_late():
    stocks = [{"isin": ISIN, "name": "Apple", "held": True, "last_ex_date": "2026-08-01", "gap_days": 91}]
    state = _run(_result(stocks=stocks), [], {}, None)["state"]
    assert _run(_result(stocks=stocks), [], {}, state)["new"] == []


def test_an_announced_next_date_clears_the_late_report():
    stocks = [{"isin": ISIN, "name": "Apple", "held": True, "last_ex_date": "2026-04-01", "gap_days": 91}]
    events = {ISIN: [_event("2026-04-01", 0.25), _event("2026-10-01", 0.25)]}
    state = _run(_result(stocks=stocks), [], events, None)["state"]
    assert _run(_result(stocks=stocks), [], events, state)["new"] == []


def test_only_your_own_positions_are_watched():
    """A watchlist entry is not owned, so nothing about it is an event."""
    state = _run(_result(holdings=[]), [], {ISIN: [_event("2026-06-08", 0.25)]}, None)["state"]
    out = _run(_result(holdings=[]), [], {ISIN: [_event("2026-06-08", 0.25), _event("2026-09-08", 0.1)]}, state)
    assert out["new"] == []


def test_upcoming_dates_stop_at_the_horizon():
    upcoming = [{"isin": ISIN, "name": "Apple", "next_ex_date": "2026-09-20", "next_pay_date": "2026-10-01"},
                {"isin": ISIN, "name": "Apple", "next_ex_date": "2026-12-20", "next_pay_date": "2027-01-01"}]
    out = _run(_result(upcoming=upcoming), [], {}, None)
    assert len(out["view"]["upcoming"]) == 1
    assert out["view"]["next_ex_date"] == "2026-09-20"


def test_the_feed_forgets_entries_older_than_the_window():
    state = _run(_result(), [], {}, None)["state"]
    old = _run(_result(), [_row("2026-09-12", rid="tx1")], {}, state)["state"]
    assert old["log"]
    later = watch_core.analyze_watch(_result(), [], {}, old, date(2027, 6, 1))
    assert later["view"]["items"] == [] and later["view"]["count"] == 0
