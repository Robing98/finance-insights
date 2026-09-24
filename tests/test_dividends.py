"""Dividend providers, analysis, benchmarks, and the dividend sensors."""
import re
import shutil
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.finance_insights import dividend_core, market_data, pytr_client
from custom_components.finance_insights.const import DOMAIN
from custom_components.finance_insights.market_data import DividendEvent

from .cards import cards, check_sources, table, table_rows

HERE = Path(__file__).parent
NESTLE = "CH0038863350"
TODAY = date(2026, 9, 15)
ECB_DFR = "KEY,FREQ,TIME_PERIOD,OBS_VALUE\nFM.B,B,2026-06-11,2.00\nFM.B,B,2026-09-11,1.75\n"
HICP = "KEY,FREQ,TIME_PERIOD,OBS_VALUE\nICP.M,M,2026-07,2.1\nICP.M,M,2026-08,2.3\n"
FX = "KEY,FREQ,CURRENCY,TIME_PERIOD,OBS_VALUE\nEXR,D,CHF,2026-09-11,0.93\nEXR,D,CHF,2026-09-12,0.94\n"


@pytest.fixture(autouse=True)
def _today(freezer):
    freezer.move_to("2026-09-15 12:00:00+02:00")


def _ecb(aioclient_mock):
    aioclient_mock.get(f"{market_data.ECB}/{market_data.SERIES['ecb_deposit_rate']}", text=ECB_DFR)
    aioclient_mock.get(f"{market_data.ECB}/{market_data.SERIES['inflation']}", text=HICP)
    aioclient_mock.get(f"{market_data.ECB}/EXR/D.CHF.EUR.SP00.A", text=FX)


async def test_nothing_leaves_the_network_by_default(hass, tmp_path, aioclient_mock):
    """A fresh account reads its CSV export and contacts nobody."""
    hass.config.config_dir = str(tmp_path)
    (tmp_path / "trade_republic").mkdir()
    shutil.copy(HERE / "sample.csv", tmp_path / "trade_republic" / "export.csv")
    entry = MockConfigEntry(domain=DOMAIN, title="Trade Republic", unique_id="tr",
                            data={"account_type": "trade_republic", "folder": "trade_republic", "use_pytr": False})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert aioclient_mock.call_count == 0
    assert hass.states.get("sensor.trade_republic_net_worth") is not None


def test_ecb_csv_and_currency():
    assert market_data.parse_ecb_csv(ECB_DFR) == [("2026-06-11", 2.0), ("2026-09-11", 1.75)]
    assert market_data.normalize_currency(52.0, "GBp") == (0.52, "GBP")


def test_merge_prefers_primary_and_keeps_old_history():
    primary = [DividendEvent(date(2026, 4, 20), 3.10, "CHF", pay_date=date(2026, 4, 24), source="eodhd")]
    history = [DividendEvent(date(2026, 4, 21), 3.10, "CHF", source="yahoo"), DividendEvent(date(2025, 4, 22), 3.05, "CHF", source="yahoo")]
    merged = market_data.merge_events(primary, history)
    assert [e.source for e in merged] == ["yahoo", "eodhd"]


def _quarterly(start_year=2019, amount=0.50, growth=0.05):
    events = []
    for y in range(start_year, 2027):
        for m in (2, 5, 8, 11):
            ex = date(y, m, 10)
            if ex <= date(2026, 11, 10):
                events.append(DividendEvent(ex, round(amount * (1 + growth) ** (y - start_year), 4), "USD",
                                            pay_date=date(y, m, 25), source="eodhd"))
    return events


def test_stock_view_quarterly_usd_payer():
    fx = dividend_core._Fx({"USD": 1.10})
    own = [{"date": "2026-08-25", "amount": 6.0, "tax": -1.6}, {"date": "2026-05-25", "amount": 6.0, "tax": -1.6}]
    s = dividend_core.stock_view("US1912161007", "Coca-Cola", _quarterly(), own, fx, TODAY,
                                 shares=10, cost=500.0, value=600.0, unrealized=100.0)
    dps_usd = 0.50 * 1.05 ** 7 * 3 + 0.50 * 1.05 ** 6  # Nov 2025 still at the 2025 rate
    assert s["frequency"] == 4
    assert s["dps_eur"] == pytest.approx(dps_usd / 1.10, abs=1e-3)
    assert s["yield_pct"] == pytest.approx(s["dps_eur"] / 60 * 100, abs=0.01)
    assert s["yield_on_cost_pct"] == pytest.approx(s["dps_eur"] / 50 * 100, abs=0.01)
    assert s["growth_pct"] == pytest.approx(5.0, abs=0.1) and s["years_without_cut"] == 6
    # Announced November dividend: not estimated.
    assert (s["next_ex_date"], s["next_pay_date"], s["estimated"]) == ("2026-11-10", "2026-11-25", False)
    assert s["received"] == 12.0 and s["tax_rate_pct"] == pytest.approx(26.7, abs=0.1)
    assert s["payback_pct"] == pytest.approx(2.4)
    assert s["years_to_payback"] == pytest.approx((500 - 12) / s["annual_income"], abs=0.1)


def test_stock_view_estimates_next_from_rhythm_and_own_payments():
    fx = dividend_core._Fx({})
    events = [DividendEvent(date(y, 4, 20), 1.0 + 0.1 * (y - 2022), "EUR", pay_date=date(y, 4, 24)) for y in range(2022, 2027)]
    s = dividend_core.stock_view("DE0007164600", "SAP", events, [], fx, TODAY, shares=5, cost=500, value=900)
    assert s["estimated"] and s["next_ex_date"].startswith("2027-04") and s["next_pay_date"]
    no_events = dividend_core.stock_view("CH0038863350", "Nestle", [], [
        {"date": "2025-04-25", "amount": 17.46, "tax": -6.11}, {"date": "2026-04-24", "amount": 17.94, "tax": -6.28}],
        fx, TODAY, shares=6, cost=550, value=500)
    assert no_events["source"] == "payments" and no_events["dps_eur"] == pytest.approx(17.94 / 6, abs=1e-3)
    assert no_events["next_pay_date"].startswith("2027-04") and no_events["estimated"]


def test_tr_cash_rate():
    rows = [
        {"datetime": "2026-07-01T00:00", "date": "2026-07-01", "type": "INTEREST_PAYMENT", "symbol": "", "amount": 10.0, "cash": 10.0},
        {"datetime": "2026-07-01T01:00", "date": "2026-07-01", "type": "CUSTOMER_INPAYMENT", "symbol": "", "amount": 5990.0, "cash": 5990.0},
        {"datetime": "2026-08-01T00:00", "date": "2026-08-01", "type": "INTEREST_PAYMENT", "symbol": "", "amount": 10.0, "cash": 10.0},
    ]
    rate = dividend_core.tr_cash_rate(rows, TODAY)
    assert rate["rate_pct"] == pytest.approx(10 / 6000 * 365 / 31 * 100, abs=0.01)


async def test_providers_parse(hass, aioclient_mock):
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    session = async_get_clientsession(hass)
    aioclient_mock.get("https://eodhd.com/api/search/CH0038863350", json=[
        {"Code": "NESN", "Exchange": "VX", "ISIN": "CH0038863350", "isPrimary": False},
        {"Code": "NESN", "Exchange": "SW", "ISIN": "CH0038863350", "isPrimary": True}])
    aioclient_mock.get("https://eodhd.com/api/div/NESN.SW", json=[
        {"date": "2026-04-20", "declarationDate": None, "recordDate": None, "paymentDate": "2026-04-24", "period": "Annual",
         "value": 3.1, "unadjustedValue": 3.1, "currency": "CHF"}])
    eod = market_data.EODHDProvider("key")
    assert await eod.lookup(session, NESTLE, "Nestle") == "NESN.SW"
    events = await eod.dividends(session, "NESN.SW", date(2025, 9, 15))
    assert events[0].pay_date == date(2026, 4, 24) and events[0].currency == "CHF"

    aioclient_mock.get("https://www.alphavantage.co/query", json={"symbol": "KO", "data": [
        {"ex_dividend_date": "2026-06-13", "declaration_date": "2026-04-30", "record_date": "2026-06-13",
         "payment_date": "2026-07-01", "amount": "0.53"},
        {"ex_dividend_date": "2026-11-28", "declaration_date": "None", "record_date": "None", "payment_date": "None",
         "amount": "0.53"}]})
    av = await market_data.AlphaVantageProvider("key").dividends(session, "KO", date(2025, 1, 1))
    assert av[1].pay_date is None and av[0].amount == 0.53

    aioclient_mock.clear_requests()
    aioclient_mock.get("https://finnhub.io/api/v1/stock/dividend", status=403, json={"error": "You don't have access"})
    with pytest.raises(market_data.NotAvailable):
        await market_data.FinnhubProvider("key").dividends(session, "NESN.SW", date(2025, 1, 1))

    aioclient_mock.get("https://query1.finance.yahoo.com/v8/finance/chart/KO", json={"chart": {"result": [
        {"meta": {"currency": "USD"}, "events": {"dividends": {"1781308800": {"amount": 0.53, "date": 1781308800}}}}]}})
    yahoo = await market_data.YahooProvider().dividends(session, "KO", date(2025, 1, 1))
    assert yahoo[0].ex_date == date(2026, 6, 13) and yahoo[0].currency == "USD"


async def test_dividend_sensors_with_budget_and_fallback(hass, tmp_path, aioclient_mock):
    hass.config.config_dir = str(tmp_path)
    (tmp_path / "trade_republic").mkdir()
    shutil.copy(HERE / "sample.csv", tmp_path / "trade_republic" / "export.csv")
    _ecb(aioclient_mock)
    # Primary provider refuses (plan without dividends), Yahoo fills in.
    aioclient_mock.get("https://finnhub.io/api/v1/search", json={"count": 1, "result": [{"symbol": "NESN.SW"}]})
    aioclient_mock.get("https://finnhub.io/api/v1/stock/dividend", status=403, json={"error": "premium"})
    aioclient_mock.get("https://query2.finance.yahoo.com/v1/finance/search", params={"q": NESTLE, "quotesCount": "5", "newsCount": "0"},
                       json={"quotes": [{"symbol": "NESN.SW", "quoteType": "EQUITY"}]})
    aioclient_mock.get("https://query1.finance.yahoo.com/v8/finance/chart/NESN.SW", json={"chart": {"result": [
        {"meta": {"currency": "CHF"}, "events": {"dividends": {
            str(ts): {"amount": amt, "date": ts} for ts, amt in ((1650412800, 2.80), (1682035200, 2.95), (1713484800, 3.00),
                                                                 (1745107200, 3.05), (1776643200, 3.10))}}}]}})
    entry = MockConfigEntry(domain=DOMAIN, title="Trade Republic", unique_id="tr",
                            data={"account_type": "trade_republic", "folder": "trade_republic", "use_pytr": False},
                            options={"dividend_provider": "finnhub", "dividend_api_key": "k", "yahoo_fallback": True,
                                     "benchmarks": True})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    div_yield = hass.states.get("sensor.trade_republic_dividend_yield")
    stock = next(s for s in div_yield.attributes["stocks"] if s["isin"] == NESTLE)
    assert stock["source"] == "yahoo" and stock["dps_eur"] == pytest.approx(3.10 / 0.94, abs=1e-3)
    assert stock["growth_pct"] > 0 and stock["received"] == pytest.approx(35.40)
    assert float(hass.states.get("sensor.trade_republic_ecb_deposit_rate").state) == 1.75
    assert float(hass.states.get("sensor.trade_republic_inflation_rate").state) == 2.3
    assert hass.states.get("sensor.trade_republic_next_dividend").state.startswith("2027-04")
    assert stock["annual_income"] == pytest.approx(6 * 3.10 / 0.94, abs=0.01)
    income = float(hass.states.get("sensor.trade_republic_dividend_income_forward").state)
    assert income == pytest.approx(sum(s["annual_income"] or 0 for s in div_yield.attributes["stocks"]), abs=0.02)
    status = hass.states.get("sensor.trade_republic_data_status").attributes["dividend_data"]
    assert any("Finnhub" in e and "plan" in e for e in status["errors"])


    from custom_components.finance_insights.dashboard import build_views, load_templates

    tab = next(v for v in build_views([entry], load_templates(), {}) if v["path"].endswith("-dividends"))
    by_attr = {c.get("attribute"): c for c in cards(tab, "table")}
    upcoming = table_rows(hass, by_attr["upcoming"])
    nestle = next(u for u in upcoming if u["name"] == "Nestle")
    assert re.match(r"2027-04-\d\d", nestle["next_ex_date"]) and re.match(r"2027-04-\d\d", nestle["next_pay_date"]) and nestle["estimated"]
    assert ["Nestle", "Depot"] in [r[:2] for r in table(hass, by_attr["ranking"])]
    assert ["2026", 17.94] in table(hass, by_attr["per_year"])
    assert not check_sources(hass, tab)

    # Second refresh within the interval: no new provider calls.
    calls = aioclient_mock.call_count
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert aioclient_mock.call_count == calls


async def test_watchlist_from_pytr(hass, tmp_path, aioclient_mock):
    hass.config.config_dir = str(tmp_path)
    (tmp_path / "tr").mkdir()
    shutil.copy(HERE / "sample.csv", tmp_path / "tr" / "export.csv")
    _ecb(aioclient_mock)
    aioclient_mock.get("https://eodhd.com/api/search/US1912161007", json=[{"Code": "KO", "Exchange": "US", "isPrimary": True}])
    aioclient_mock.get("https://eodhd.com/api/div/KO.US", json=[
        {"date": f"{y}-{m:02d}-13", "paymentDate": f"{y}-{m:02d}-28", "value": 0.51, "unadjustedValue": 0.51, "currency": "USD"}
        for y, m in ((2025, 11), (2026, 3), (2026, 6), (2026, 9))])
    for isin in ("CH0038863350", "IE00B4L5Y983", "LU1681045370", "US72919P2020"):
        aioclient_mock.get(f"https://eodhd.com/api/search/{isin}", json=[])
    aioclient_mock.get(f"{market_data.ECB}/EXR/D.USD.EUR.SP00.A", text="CURRENCY,TIME_PERIOD,OBS_VALUE\nUSD,2026-09-12,1.10\n")
    live = dict(positions=[], cash=100.0, timeline_updated=True,
                watchlist=[{"isin": "US1912161007", "name": "Coca-Cola", "price": 62.0}])
    entry = MockConfigEntry(domain=DOMAIN, title="Trade Republic", unique_id="tr2",
                            data={"account_type": "trade_republic", "folder": "tr", "use_pytr": True, "phone": "+491", "pin": "1"},
                            options={"dividend_provider": "eodhd", "dividend_api_key": "k", "yahoo_fallback": False,
                                     "include_watchlist": True})
    entry.add_to_hass(hass)
    with patch("custom_components.finance_insights.async_process_requirements"), \
         patch.object(pytr_client, "fetch", return_value=live) as fetch, \
         patch("custom_components.finance_insights.tr_core.rows_from_pytr", return_value=[]):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert fetch.call_args.kwargs["with_watchlist"] is True
    attrs = hass.states.get("sensor.trade_republic_dividend_yield").attributes
    ko = attrs["watchlist"][0]
    assert ko["name"] == "Coca-Cola" and not ko["held"]
    assert ko["yield_pct"] == pytest.approx(0.51 * 4 / 1.10 / 62 * 100, abs=0.01)
    assert any(r["isin"] == "US1912161007" for r in attrs["ranking"])


def test_cagr_ignores_a_partial_first_year():
    """A position bought in November holds one payment that year, not four."""
    from custom_components.finance_insights.dividend_core import _Fx, stock_view

    def event(day: str, amount: float):
        return DividendEvent(ex_date=date.fromisoformat(day), pay_date=date.fromisoformat(day),
                             amount=amount, currency="EUR", source="test")

    full = [event(f"{year}-{month:02d}-15", 1.0) for year in (2024, 2025) for month in (2, 5, 8, 11)]
    partial = [event("2023-11-15", 1.0)]
    today, fx = date(2026, 6, 15), _Fx({})

    # Four payments a year, unchanged: no growth. The stub year must not turn that into +300 %.
    with_stub = stock_view("DE0001", "Example", partial + full, [], fx, today)
    assert with_stub["growth_pct"] in (None, 0) or abs(with_stub["growth_pct"]) < 1

    # Three complete years of four payments each, still flat.
    complete = [event(f"{year}-{month:02d}-15", 1.0) for year in (2023, 2024, 2025) for month in (2, 5, 8, 11)]
    assert abs(stock_view("DE0001", "Example", complete, [], fx, today)["growth_pct"] or 0) < 1
