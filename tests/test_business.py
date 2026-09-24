"""Net, VAT, and profit for a business account."""
from datetime import date

import pytest

from custom_components.finance_insights import business_core

TODAY = date(2026, 9, 15)
RULES = business_core.read_vat_rules(
    "pattern,category,vat\n"
    "HOSTING,IT and hosting,19\n"
    "FAHRKARTE,Travel,7\n"
    "VERSICHERUNG,Insurance,0\n"
    "RECHNUNG,Revenue,19\n")


def _row(day: str, amount: float, purpose: str, kind: str, merchant="Someone"):
    return {"date": date.fromisoformat(day), "month": day[:7], "year": int(day[:4]), "amount": amount,
            "kind": kind, "merchant": merchant, "purpose": purpose, "booking_text": "", "counterparty": "",
            "pending": False, "category": None}


ROWS = [
    _row("2026-07-05", 1190.0, "RECHNUNG 2026-07 Webshop", "income", "Kunde A"),
    _row("2026-08-10", 2380.0, "RECHNUNG 2026-08", "income", "Kunde B"),
    _row("2026-08-11", -119.0, "HOSTING Server", "expense", "Hoster"),
    _row("2026-08-12", -107.0, "FAHRKARTE Bahn", "expense", "Bahn"),
    _row("2026-08-13", -50.0, "VERSICHERUNG Haftpflicht", "expense", "Versicherer"),
    _row("2026-08-14", -80.0, "EDEKA", "expense", "Edeka"),
    _row("2026-09-01", 595.0, "RECHNUNG 2026-09", "income", "Kunde A"),
    _row("2026-09-02", -200.0, "Privatentnahme", "internal", "Robin"),
]


def _analyze(**kw):
    return business_core.analyze_business(ROWS, TODAY, rules=RULES, **kw)


def test_gross_splits_into_net_and_vat():
    assert business_core.split(119.0, 19) == pytest.approx((100.0, 19.0))
    assert business_core.split(107.0, 7) == pytest.approx((100.0, 7.0))
    assert business_core.split(50.0, 0) == (50.0, 0.0)


def test_vat_due_is_what_was_collected_minus_what_was_paid():
    august = next(m for m in _analyze()["months"] if m["month"] == "2026-08")
    assert august["revenue_net"] == pytest.approx(2000.0)
    assert august["vat_collected"] == pytest.approx(380.0)
    # 19 on hosting, 7 on the ticket, nothing on the insurance.
    assert august["input_vat"] == pytest.approx(19.0 + 7.0)
    assert august["vat_due"] == pytest.approx(354.0)
    assert august["profit"] == pytest.approx(2000.0 - (100.0 + 100.0 + 50.0))


def test_a_booking_without_a_rule_is_reported_not_guessed():
    result = _analyze()
    august = next(m for m in result["months"] if m["month"] == "2026-08")
    assert august["unassigned_expense"] == pytest.approx(80.0)
    assert august["expenses_gross"] == pytest.approx(119.0 + 107.0 + 50.0)  # the 80 is not in here
    assert [i["merchant"] for i in result["unassigned_items"]] == ["Edeka"]


def test_private_withdrawals_are_left_out():
    assert all(m["expenses_gross"] < 400 for m in _analyze()["months"])
    september = next(m for m in _analyze()["months"] if m["month"] == "2026-09")
    assert september["expenses_gross"] == 0.0 and september["unassigned_expense"] == 0.0


def test_quarters_add_up_the_months():
    result = _analyze()
    q3 = next(q for q in result["quarters"] if q["quarter"] == "2026-Q3")
    months = [m for m in result["months"] if m["month"] in ("2026-07", "2026-08", "2026-09")]
    assert q3["vat_due"] == pytest.approx(sum(m["vat_due"] for m in months))
    assert q3["profit"] == pytest.approx(sum(m["profit"] for m in months))


def test_a_small_business_has_no_vat_at_all():
    result = _analyze(small_business=True)
    assert result["year"]["vat_collected"] == 0.0 and result["year"]["input_vat"] == 0.0
    assert result["year"]["revenue_net"] == result["year"]["revenue_gross"]
    assert result["year"]["unassigned"] == 0.0  # without VAT nothing needs a rate
    assert result["year"]["profit"] == pytest.approx(1190.0 + 2380.0 + 595.0 - (119.0 + 107.0 + 50.0 + 80.0))


def test_the_reserve_follows_the_profit():
    result = _analyze(reserve_pct=30)
    assert result["reserve"] == pytest.approx(round(result["year"]["profit"] * 0.3, 2))
    assert _analyze(reserve_pct=0)["reserve"] == 0.0


def test_a_default_rate_covers_what_no_rule_matches():
    result = _analyze(default_rate=19)
    assert result["year"]["unassigned"] == 0.0
    august = next(m for m in result["months"] if m["month"] == "2026-08")
    assert august["input_vat"] == pytest.approx(19.0 + 7.0 + business_core.split(80.0, 19)[1], abs=0.01)


def test_rules_without_a_vat_column_are_ignored_here():
    assert business_core.read_vat_rules("pattern,category\nEDEKA,Groceries\n") == []
    assert len(RULES) == 4


# ---------------------------------------------------------------- the account option

import shutil  # noqa: E402
from pathlib import Path  # noqa: E402

from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402

from custom_components.finance_insights.const import DOMAIN  # noqa: E402

HERE = Path(__file__).parent


@pytest.fixture(autouse=True)
def _today(freezer):
    freezer.move_to("2026-09-15 12:00:00+02:00")


async def _account(hass, tmp_path, options=None, rules=None):
    hass.config.config_dir = str(tmp_path)
    folder = tmp_path / "sparkasse"
    folder.mkdir(exist_ok=True)
    shutil.copy(HERE / "sparkasse_sample.csv", folder / "export.csv")
    if rules is not None:
        (folder / "categories.csv").write_text(rules, encoding="utf-8")
    entry = MockConfigEntry(domain=DOMAIN, title="Sparkasse", unique_id="bank", options=options or {},
                            data={"account_type": "bank", "name": "Sparkasse", "folder": "sparkasse", "use_fints": False})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_a_normal_account_gets_no_business_sensors(hass, tmp_path):
    await _account(hass, tmp_path)
    assert hass.states.get("sensor.sparkasse_balance") is not None
    assert hass.states.get("sensor.sparkasse_business_profit") is None


async def test_the_option_adds_the_sensors_and_reads_the_vat_column(hass, tmp_path):
    await _account(hass, tmp_path, options={"business": True, "tax_reserve": 30},
                   rules="pattern,category,vat\nMIETE,Rent and housing,0\nSTROM,Utilities,19\n")
    profit = hass.states.get("sensor.sparkasse_business_profit")
    assert profit is not None and profit.state not in ("unknown", "unavailable")
    unassigned = hass.states.get("sensor.sparkasse_business_unassigned")
    # Everything the two rules do not cover is reported instead of guessed.
    assert float(unassigned.state) > 0
    assert unassigned.attributes["items"]
    reserve = hass.states.get("sensor.sparkasse_business_reserve")
    assert reserve.attributes["percent"] == 30


async def test_the_business_fields_appear_only_after_the_switch(hass, tmp_path):
    """The extra fields would be noise on a private account, so they show up once it is a business one."""
    entry = await _account(hass, tmp_path)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert "business" in result["data_schema"].schema
    assert "small_business" not in result["data_schema"].schema

    await hass.config_entries.options.async_configure(
        result["flow_id"], {"scan_minutes": 60, "fints_hours": 12, "transfer_keywords": "Trade Republic",
                            "offset_rules": "", "business": True})
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert {"small_business", "vat_default", "tax_reserve"} <= set(result["data_schema"].schema)
    assert hass.states.get("sensor.sparkasse_business_profit") is not None


async def test_the_tab_appears_only_for_a_business_account(hass, tmp_path):
    from custom_components.finance_insights.dashboard import build_views, load_language, load_templates

    from .cards import cards

    private = await _account(hass, tmp_path)
    templates = load_templates()
    assert not [v for v in build_views([private], templates, {}) if v["path"].endswith("-business")]

    hass.config_entries.async_update_entry(private, options={"business": True, "tax_reserve": 30})
    await hass.async_block_till_done()
    views = build_views([private], templates, {}, load_language("de"))
    tab = next(v for v in views if v["path"].endswith("-business"))
    assert tab["title"] == "Geschäft"

    figures = cards(tab, "kpis")[0]["items"]
    assert [i["entity"] for i in figures][:2] == ["sensor.sparkasse_business_profit",
                                                  "sensor.sparkasse_business_revenue_net"]
    text = str(tab)
    assert "Ist-Versteuerung" in text and "Soll-Versteuerung" in text  # the limits are on the tab, not only in the README
    assert "Zahllast" in text and "Vorsteuer" in text
