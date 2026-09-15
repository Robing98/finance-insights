"""Sparkasse CSV parsing, classification, recurring payments, and transfer matching."""
from datetime import date
from pathlib import Path

from custom_components.finance_insights import bank_core, overview_core

SAMPLE = Path(__file__).parent / "sparkasse_sample.csv"
IBAN = "DE12500500000123456789"
TODAY = date(2026, 9, 15)


def _rows():
    return bank_core.merge_exports([bank_core.read_sparkasse_csv(SAMPLE.read_bytes())])


def test_parse_camt_export():
    rows = _rows()
    assert len(rows) == 288
    assert all(r["account"] == IBAN for r in rows)
    assert sum(r["pending"] for r in rows) == 1
    assert bank_core.parse_amount("-1.143,41") == -1143.41
    assert bank_core.parse_date("03.09.26") == date(2026, 9, 3)


def test_overlapping_exports_are_merged():
    data = SAMPLE.read_bytes()
    lines = data.split(b"\n")
    first = b"\n".join(lines[:150])
    second = b"\n".join([lines[0], *lines[100:]])
    merged = bank_core.merge_exports([bank_core.read_sparkasse_csv(first), bank_core.read_sparkasse_csv(second)])
    assert len(merged) == len(_rows())


def test_classification_and_analysis():
    rows = bank_core.classify(_rows(), own_ibans={IBAN}, keywords=["Trade Republic"])
    kinds = {r["counterparty"]: r["kind"] for r in rows}
    assert kinds["Trade Republic Bank GmbH"] == "internal"
    res = bank_core.analyze_bank(rows, TODAY)
    assert res["to_depot_12m"] == 6000.0
    assert res["income_kinds_12m"] == {"Salary": 23100.0}
    assert res["last_salary"]["amount"] == 2100.0
    assert res["balance"] is None and res["missing_balance"] == [IBAN]
    cadences = {r["name"]: r["cadence"] for r in res["recurring"]}
    assert cadences["HAUSVERWALTUNG BEISPIEL"] == "monthly"
    assert cadences["HUK-COBURG VERSICHERUNG"] == "quarterly"
    assert res["groups_12m"]["Housing"] > 0
    assert [y["year"] for y in res["by_year"]] == [2025, 2026]


def test_paypal_merchant_and_user_rules():
    row = {"counterparty": "PayPal Europe S.a.r.l. et Cie S.C.A", "purpose": "1234 PP.5678.PP . Spotify AB, Ihr Einkauf bei Spotify AB",
           "booking_text": "FOLGELASTSCHRIFT", "amount": -10.99}
    assert bank_core.merchant_name(row) == "SPOTIFY AB"
    assert bank_core.categorize(row) == "Subscriptions"
    rules = bank_core.read_rules_csv("pattern;category\nspotify;Music\n")
    assert bank_core.categorize(row, rules) == "Music"


def test_balance_anchor_rolls_forward():
    rows = bank_core.classify(_rows(), own_ibans={IBAN})
    anchors = bank_core.read_balance_csv(f"iban;date;balance\n{IBAN};01.01.2026;1.000,00\n")
    res = bank_core.analyze_bank(rows, TODAY, balance_anchors=anchors)
    booked_after = sum(r["amount"] for r in rows if date(2026, 1, 1) < r["date"] <= TODAY and not r["pending"])
    assert res["balance_source"].startswith("anchor")
    assert res["balance"] == round(1000 + booked_after, 2)
    live = bank_core.analyze_bank(rows, TODAY, balances={IBAN: 4321.0})
    assert live["balance"] == 4321.0 and live["balance_source"] == "live"


def test_transfer_matching_by_amount_and_date():
    rows = [
        {"id": "a", "date": date(2026, 3, 2), "amount": -333.33, "pending": False},
        {"id": "b", "date": date(2026, 3, 20), "amount": -333.33, "pending": False},
    ]
    flows = [{"id": "t1", "date": date(2026, 3, 4), "amount": 333.33}]
    bank_ids, broker_ids = bank_core.match_transfers(rows, flows)
    assert bank_ids == {"a"} and broker_ids == {"t1"}


def test_overview_combines_accounts():
    rows = bank_core.classify(_rows(), own_ibans={IBAN})
    bank = bank_core.analyze_bank(rows, TODAY, balances={IBAN: 2000.0})
    broker = {"summary": {"cash": 500.0, "holdings_value": 10000.0},
              "monthly": [{"month": "2026-09", "income": 12.0, "spending": 30.0}]}
    ov = overview_core.build_overview([("Sparkasse", bank)], [("Trade Republic", broker)], TODAY)
    assert ov["net_worth"] == 12500.0 and ov["liquid"] == 2500.0
    assert ov["spending_month"] == round(bank["spending_month"] + 30.0, 2)
    assert ov["missing_balances"] == []
