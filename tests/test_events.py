"""Events for automations."""
import pytest
from homeassistant.core import Event, callback

from custom_components.finance_insights.events import EVENT_HOLDING, EVENT_RECURRING, EVENT_TRANSACTION

from .test_integration import SPK_SAMPLE, TR_SAMPLE, _bank_entry, _copy, _setup, _tr_entry

HEAD = SPK_SAMPLE.read_text(encoding="utf-8").splitlines()[0]


def _row(day, payee, amount, purpose, text="FOLGELASTSCHRIFT", creditor="DE00ZZZ00000NETFLIX", mandate="NF-1"):
    return (f'"DE12500500000123456789";"{day}";"{day}";"{text}";"{purpose}";"{creditor}";"{mandate}";"NOTPROVIDED";"";"";"";'
            f'"{payee}";"DE00100000000000000099";"";"{amount}";"EUR";"Umsatz gebucht"')


@pytest.fixture(autouse=True)
def _today(freezer):
    freezer.move_to("2026-09-15 12:00:00+02:00")


async def test_new_bookings_and_subscriptions_fire_events(hass, tmp_path):
    hass.config.config_dir = str(tmp_path)
    _copy(tmp_path, SPK_SAMPLE, "sparkasse")
    fired: list[Event] = []
    hass.bus.async_listen(EVENT_TRANSACTION, callback(lambda e: fired.append(e)))
    subs: list[Event] = []
    hass.bus.async_listen(EVENT_RECURRING, callback(lambda e: subs.append(e)))
    entry = _bank_entry()
    await _setup(hass, entry)
    assert fired == [] and subs == []  # setup only records what exists

    extra = [_row("15.07.26", "Netflix", "-12,99", "Abo Juli"), _row("15.08.26", "Netflix", "-12,99", "Abo August"),
             _row("15.09.26", "Netflix", "-12,99", "Abo September")]
    (tmp_path / "sparkasse" / "new.csv").write_text("\n".join([HEAD, *extra]) + "\n", encoding="utf-8")
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    # July is older than the 45-day window, so only August and September fire.
    assert [e.data["date"] for e in fired] == ["2026-08-15", "2026-09-15"]
    data = fired[-1].data
    assert data["amount"] == -12.99 and data["kind"] == "expense" and data["name"] == "NETFLIX"
    assert data["account"] == "Sparkasse" and data["entry_id"] == entry.entry_id
    assert [e.data["name"] for e in subs] == ["NETFLIX"]

    # Nothing new: nothing fires again.
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert len(fired) == 2 and len(subs) == 1


NESTLE = "CH0038863350"


def _dividend(day: str, amount: float) -> dict:
    return {"ex_date": day, "amount": amount, "currency": "CHF", "pay_date": None, "record_date": None,
            "declared_date": None, "source": "test"}


async def test_a_dividend_cut_on_a_holding_fires_an_event(hass, tmp_path):
    """No provider is configured here, so the events are put into the cache the way a fetch would."""
    hass.config.config_dir = str(tmp_path)
    _copy(tmp_path, TR_SAMPLE, "trade_republic")
    fired: list[Event] = []
    hass.bus.async_listen(EVENT_HOLDING, callback(lambda e: fired.append(e)))
    entry = _tr_entry()
    await _setup(hass, entry)
    coordinator = entry.runtime_data
    assert fired == []

    cache = coordinator.market.data.setdefault("events", {})
    cache[NESTLE] = {"fetched": "2026-09-15T10:00:00", "name": "Nestle", "sources": ["test"],
                     "events": [_dividend("2026-06-08", 3.0)]}
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert fired == []  # a position whose dividends were not recorded before is recorded first

    cache[NESTLE]["events"].append(_dividend("2026-09-08", 2.4))
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert [e.data["kind"] for e in fired] == ["dividend_cut"]
    assert fired[0].data["change_pct"] == -20.0 and fired[0].data["name"] == "Nestle"
    assert fired[0].data["account"] == "Trade Republic" and "id" not in fired[0].data

    events = hass.states.get("sensor.trade_republic_holding_events")
    assert events.state == "1" and events.attributes["items"][0]["isin"] == NESTLE

    # Nothing new: nothing fires again, and the feed keeps the entry.
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert len(fired) == 1 and hass.states.get("sensor.trade_republic_holding_events").state == "1"


async def test_the_portfolio_checks_measure_the_sample_account(hass, tmp_path):
    hass.config.config_dir = str(tmp_path)
    _copy(tmp_path, TR_SAMPLE, "trade_republic")
    await _setup(hass, _tr_entry())
    checks = hass.states.get("sensor.trade_republic_portfolio_checks")
    by_key = {c["key"]: c for c in checks.attributes["checks"]}
    # Every position in the sample is valued from an old trade, and the largest one is over half the depot.
    assert by_key["stale_prices"]["value"] == 6
    assert by_key["concentration"]["name"].startswith("Core MSCI World")
    assert by_key["concentration"]["level"] == "watch" and by_key["concentration"]["unit"] == "%"
    assert float(hass.states.get("sensor.trade_republic_largest_position").state) > 50
    assert checks.state == str(sum(1 for c in by_key.values() if c["level"] == "watch"))
    assert set(by_key) >= {"concentration", "top5", "stale_prices", "fees"}
