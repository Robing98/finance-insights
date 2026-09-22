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
    assert res["to_depot_12m"] == 5750.0  # 6000 out, 250 back
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


HEADER = ('"Auftragskonto";"Buchungstag";"Valutadatum";"Buchungstext";"Verwendungszweck";"Glaeubiger ID";"Mandatsreferenz";'
          '"Kundenreferenz (End-to-End)";"Sammlerreferenz";"Lastschrift Ursprungsbetrag";"Auslagenersatz Ruecklastschrift";'
          '"Beguenstigter/Zahlungspflichtiger";"Kontonummer/IBAN";"BIC (SWIFT-Code)";"Betrag";"Waehrung";"Info";"Kategorie"')
PP = "PayPal Europe S.a.r.l. et Cie S.C.A"


def _line(day, text, purpose, who, iban, bic, amount, category, cred="", mandate=""):
    return f'"{IBAN}";"{day}";"{day}";"{text}";"{purpose}";"{cred}";"{mandate}";"";"";"";"";"{who}";"{iban}";"{bic}";"{amount}";"EUR";"Umsatz gebucht";"{category}"'


def test_newer_export_with_bic_and_bank_category():
    lines = [HEADER]
    for m in ("06", "07", "08"):
        lines.append(_line(f"23.{m}.26", "FOLGELASTSCHRIFT", "1/PP.1.PP/. Discord Inc, Ihr Einkauf bei Discord Inc ", PP,
                           "LU00000000000000000001", "PPLXLUL2", "-2,99", "Freizeit und Unterhaltung", "LU96ZZZ1", "PP-MANDATE"))
        lines.append(_line(f"28.{m}.26", "GUTSCHR. UEBERWEISUNG", f"Gehalt {m}/2026 ", "Beispiel GmbH",
                           "DE00300000000000000006", "HELADEF1", "1500,00", "Einkommen"))
    lines += [
        _line("29.08.26", "ECHTZEIT-UEBERWEISUNG", " DATUM 29.08.2026 ", "Max Muster", "DE00100123450000000009", "TRBKDEBBXXX", "-700,00", "Geldanlage"),
        _line("26.08.26", "ECHTZEIT-GUTSCHRIFT", " ", "Max Muster", "DE00100123450000000009", "TRBKDEBBXXX", "50,00", "Geldanlage"),
        _line("10.08.26", "FOLGELASTSCHRIFT", "2/PP.1.PP/. , Ihr Einkauf bei ", PP, "LU00000000000000000001", "PPLXLUL2", "-7,50", "Einkäufe", "LU96ZZZ1", "PP-MANDATE"),
        _line("14.08.26", "GUTSCHR. UEBERWEISUNG", ". Shop GmbH, Ihr Einkauf bei Shop GmbH/ABBUCHUNG VOM PAYPAL-KONTO ", PP, "LU00000000000000000001", "PPLXLUL2", "1,00", "Einkäufe"),
        _line("28.07.26", "FOLGELASTSCHRIFT", "3/PP.1.PP/. www.steampowered.com, Ihr Einkauf bei www.steampowered.com ", PP, "LU00000000000000000001", "PPLXLUL2", "-15,90", "Einkäufe", "LU96ZZZ1", "PP-MANDATE"),
        _line("13.08.26", "ONLINE-UEBERWEISUNG", "Rechnung 42 ", "Praxis Beispiel", "DE00300000000000000010", "COBADEFF", "-64,68", "Gesundheit und Wellness"),
        _line("02.08.26", "ONLINE-UEBERWEISUNG", "Rechnung 43 ", "Irgendwer", "DE00300000000000000011", "COBADEFF", "-12,00", "Bildung und Erziehung"),
    ]
    rows = bank_core.classify(bank_core.read_sparkasse_csv("\r\n".join(lines).encode("cp1252")), own_ibans={IBAN}, keywords=[])
    by_purpose = {r["purpose"].strip()[:12]: r for r in rows}
    assert rows[0]["counterparty_bic"] == "PPLXLUL2" and "bank_category" in rows[0]

    depot = [r for r in rows if r["counterparty"] == "Max Muster"]
    assert {r["kind"] for r in depot} == {"internal"}
    merchants = {r["merchant"] for r in rows}
    assert {"DISCORD INC", "WWW.STEAMPOWERED.COM", "PAYPAL", "SHOP GMBH"} <= merchants
    refund = next(r for r in rows if r["amount"] == 1.0)
    assert refund["kind"] == "expense"
    assert by_purpose["Rechnung 43"]["category"] == "Education"

    res = bank_core.analyze_bank(rows, date(2026, 9, 15))
    assert res["to_depot_12m"] == 650.0
    assert res["income_kinds_12m"] == {"Salary": 4500.0}
    assert res["months_12m"] < 4 and res["avg_income_12m"] > 1000
    assert [r["name"] for r in res["recurring"]] == ["DISCORD INC"]


def test_offset_rules_net_credits_against_a_category():
    lines = [HEADER,
             _line("06.07.26", "ECHTZEIT-UEBERWEISUNG", "Rueckmeldung ", "Technische Hochschule Mittelhessen", "DE00500000000000000001", "HELADEFF", "-355,00", "Bildung und Erziehung"),
             _line("06.07.26", "ECHTZEIT-GUTSCHRIFT", "Semester ", "Eltern Muster", "DE00500000000000000002", "GENODEF1", "360,00", "Sonstiges")]
    rows = bank_core.read_sparkasse_csv("\r\n".join(lines).encode("cp1252"))
    rules = bank_core.parse_offset_rules("semester => education\nbad line\nFoo;Bar")
    assert [cat for _, cat in rules] == ["Education", "Bar"]
    res = bank_core.analyze_bank(bank_core.classify(rows, own_ibans={IBAN}, offset_rules=rules), date(2026, 7, 20))
    assert res["income_month"] == 0
    assert res["spending_month"] == -5.0
    assert res["categories_12m"] == [["Education", -5.0, 2]]
    assert [m[0] for m in res["merchants_month"]] == ["TECHNISCHE HOCHSCHULE MITTELHESSEN"]


def test_fints_product_version_is_integration_version():
    import json

    from custom_components.finance_insights import fints_client

    manifest = json.loads((Path(fints_client.__file__).parent / "manifest.json").read_text())
    assert fints_client.product_version() == manifest["version"][:5]
    assert len(fints_client.product_version()) <= 5


def test_cash_forecast_from_fixed_costs_salary_and_spending():
    from custom_components.finance_insights import bank_core as bc
    rows = bc.classify(bc.read_sparkasse_csv((Path(__file__).parent / "sparkasse_sample.csv").read_bytes()))
    today = date(2026, 9, 15)
    result = bc.analyze_bank(rows, today, balance_anchors={"DE12500500000123456789": (date(2026, 9, 1), 2500.0)})
    f = result["forecast"]
    names = [i["name"] for i in f["items"]]
    # Rent, the savings plan to the depot, and the salary are all in the next 30 days.
    assert "HAUSVERWALTUNG BEISPIEL" in names and "TRADE REPUBLIC BANK" in names
    assert f["next_salary"]["date"] == "2026-09-28" and f["next_salary"]["amount"] == 2100
    assert len(f["series"]) == 31 and f["series"][0]["balance"] == f["start"]
    assert f["low"] <= f["start"] and f["low_date"] < f["next_salary"]["date"]
    expected_end = f["start"] + sum(i["amount"] for i in f["items"]) - 30 * f["daily_variable"]
    assert abs(f["end"] - expected_end) < 0.5
    assert bc.forecast_cash(rows, [], None, today) is None


def test_bank_search():
    from custom_components.finance_insights import banks
    assert banks.bank_code_from("DE95 5065 0023 0100 0000 00") == "50650023"
    assert banks.bank_code_from("50650023") == "50650023" and banks.bank_code_from("Sparkasse") is None
    assert [b["name"] for b in banks.search("sparkasse hanau")][:2] == ["SPARKASSE HANAU", "Sparkasse Hanauerland"]
    assert banks.search("50650023")[0]["bic"] == "HELADEF1HAN"
    assert banks.search("   ") == []
