"""Events for automations."""
import pytest
from homeassistant.core import Event, callback

from custom_components.finance_insights.events import EVENT_RECURRING, EVENT_TRANSACTION

from .test_integration import SPK_SAMPLE, _bank_entry, _copy, _setup

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
