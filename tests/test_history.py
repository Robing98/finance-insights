"""The daily history rebuilt from the exports, and the statistics it writes."""
import shutil
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.finance_insights import bank_core, history, tr_core
from custom_components.finance_insights.backfill import statistic_id
from custom_components.finance_insights.const import DOMAIN, SERVICE_BACKFILL_HISTORY

HERE = Path(__file__).parent
TODAY = date(2026, 9, 15)


@pytest.fixture(autouse=True)
def _today(freezer):
    freezer.move_to("2026-09-15 12:00:00+02:00")


def _tr_rows():
    return tr_core.read_tr_csv((HERE / "sample.csv").read_text(encoding="utf-8"))


def test_broker_history_ends_where_the_analysis_does():
    rows = _tr_rows()
    series, unpriced = history.broker_history(rows, TODAY)
    summary = tr_core.analyze(rows, today=TODAY)["summary"]
    assert series[0]["date"].isoformat() == rows[0]["date"]
    assert series[-1]["date"] == TODAY
    assert series[-1]["cash"] == round(summary["cash_derived"], 2)
    assert series[-1]["contributions"] == round(summary["net_contributions"], 2)
    assert series[-1]["cost"] == round(summary["holdings_cost"], 2)
    assert unpriced == []


def test_broker_history_covers_every_day_and_starts_at_zero():
    series, _ = history.broker_history(_tr_rows(), TODAY)
    days = {p["date"] for p in series}
    assert len(days) == len(series) == (TODAY - series[0]["date"]).days + 1
    assert series[0]["cash"] >= 0  # the first day starts from an empty account


def test_broker_history_without_rows():
    assert history.broker_history([], TODAY) == ([], [])


def test_broker_history_reports_holdings_without_a_price():
    rows = tr_core.read_tr_csv(
        "datetime,date,account_type,category,type,asset_class,name,symbol,shares,price,amount,fee,tax,currency\n"
        "2026-01-02T10:00:00.000Z,2026-01-02,DEFAULT,DELIVERY,FREE_RECEIPT,STOCK,Example AG,DE0001,5,,,,,EUR\n")
    series, unpriced = history.broker_history(rows, TODAY)
    assert unpriced == ["Example AG"]
    assert series[-1]["cost"] == 0.0  # what it cost is not in the export


def _bank_rows():
    rows = bank_core.read_sparkasse_csv((HERE / "sparkasse_sample.csv").read_bytes())
    return bank_core.classify(rows)


def test_bank_history_walks_back_from_the_current_balance():
    rows = _bank_rows()
    series = history.bank_history(rows, 1000.0, TODAY)
    assert series[-1] == {"date": TODAY, "balance": 1000.0}
    first_day = series[0]["date"]
    booked = sum(r["amount"] for r in rows if not r["pending"] and r["date"] > first_day)
    assert series[0]["balance"] == pytest.approx(1000.0 - booked, abs=0.01)


def test_bank_history_needs_a_balance():
    assert history.bank_history(_bank_rows(), None, TODAY) == []


# ---------------------------------------------------------------- the service

async def _setup(hass, entry):
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_backfill_writes_statistics_per_account(hass, tmp_path):
    hass.config.config_dir = str(tmp_path)
    hass.config.components.add("recorder")
    (tmp_path / "trade_republic").mkdir()
    shutil.copy(HERE / "sample.csv", tmp_path / "trade_republic" / "export.csv")
    await _setup(hass, MockConfigEntry(domain=DOMAIN, title="Trade Republic", unique_id="tr",
                                       data={"account_type": "trade_republic", "folder": "trade_republic", "use_pytr": False}))

    with patch("homeassistant.components.recorder.statistics.async_add_external_statistics") as write:
        result = await hass.services.async_call(DOMAIN, SERVICE_BACKFILL_HISTORY, {}, blocking=True, return_response=True)

    account = result["accounts"][0]
    assert account["account"] == "Trade Republic"
    assert account["statistics"] == [statistic_id("trade_republic", s)
                                     for s in ("broker_cash", "contributions", "invested_cost")]
    assert account["days"] > 1 and account["last"] == TODAY.isoformat()
    assert write.call_count == 3

    series, _ = history.broker_history(_tr_rows(), TODAY)
    metadata, points = write.call_args_list[0].args[1], list(write.call_args_list[0].args[2])
    assert metadata["statistic_id"] == statistic_id("trade_republic", "broker_cash")
    assert metadata["source"] == DOMAIN and metadata["unit_of_measurement"] == "EUR" and metadata["has_sum"] is False
    assert len(points) == len(series) == account["days"]
    # Statistics start on the hour, and every point carries one day's value.
    assert all(p["start"].minute == 0 and p["start"].second == 0 for p in points)
    assert all(p["mean"] == p["min"] == p["max"] for p in points)
    assert points[-1]["mean"] == series[-1]["cash"]


async def test_backfill_without_a_recorder_writes_nothing(hass, tmp_path):
    hass.config.config_dir = str(tmp_path)
    (tmp_path / "trade_republic").mkdir()
    shutil.copy(HERE / "sample.csv", tmp_path / "trade_republic" / "export.csv")
    await _setup(hass, MockConfigEntry(domain=DOMAIN, title="Trade Republic", unique_id="tr",
                                       data={"account_type": "trade_republic", "folder": "trade_republic", "use_pytr": False}))
    result = await hass.services.async_call(DOMAIN, SERVICE_BACKFILL_HISTORY, {}, blocking=True, return_response=True)
    assert result["accounts"][0]["statistics"] == []


async def test_net_worth_names_the_statistics_of_its_accounts(hass, tmp_path):
    hass.config.config_dir = str(tmp_path)
    (tmp_path / "trade_republic").mkdir()
    shutil.copy(HERE / "sample.csv", tmp_path / "trade_republic" / "export.csv")
    await _setup(hass, MockConfigEntry(domain=DOMAIN, title="Trade Republic", unique_id="tr",
                                       data={"account_type": "trade_republic", "folder": "trade_republic", "use_pytr": False}))
    await _setup(hass, MockConfigEntry(domain=DOMAIN, title="Finance overview", unique_id="ov",
                                       data={"account_type": "overview"}))
    state = hass.states.get("sensor.finance_overview_net_worth")
    assert state.attributes["history_statistics"] == [statistic_id("trade_republic", "contributions")]
