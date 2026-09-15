"""The pytr adapter splits fees and taxes back out of timeline totals."""
from custom_components.traderepublic_insights import tr_core


def _trade(eid, ts, subtitle, value, shares, fee, tax=None):
    data = [{"title": "Aktien", "detail": {"text": shares}}, {"title": "Gebühr", "detail": {"text": fee}}]
    if tax:
        data.append({"title": "Steuer", "detail": {"text": tax}})
    return {"id": eid, "timestamp": ts, "title": "Apple", "subtitle": subtitle, "eventType": "TRADING_TRADE_EXECUTED",
            "icon": "logos/US0378331005/v2", "amount": {"value": value, "currency": "EUR"},
            "details": {"sections": [{"title": "Übersicht", "data": data}]}}


def test_trades_and_card_spending():
    events = [
        _trade("1", "2026-01-02T10:00:00.000+0000", "Kauforder", -101.0, "0,5", "1,00 €"),
        {"id": "2", "timestamp": "2026-01-05T10:00:00.000+0000", "title": "REWE", "subtitle": "",
         "eventType": "CARD_TRANSACTION", "amount": {"value": -12.5, "currency": "EUR"}, "details": {"sections": []}},
        _trade("3", "2026-02-02T10:00:00.000+0000", "Verkaufsorder", 109.0, "0,5", "1,00 €", "2,00 €"),
    ]
    rows = tr_core.rows_from_pytr(events)
    assert [r["type"] for r in rows] == ["BUY", "CARD_TRANSACTION", "SELL"]
    res = tr_core.analyze(rows)
    assert res["realized"][0]["gain"] == 10.0
    assert res["realized"][0]["tax"] == -2.0
    assert res["summary"]["spending"] == 12.5
    assert res["summary"]["cash"] == -101.0 - 12.5 + 109.0


def test_merge_keeps_csv_history():
    csv_rows = tr_core.read_tr_csv(str(__import__("pathlib").Path(__file__).parent / "sample.csv"))
    live = tr_core.rows_from_pytr([_trade("9", "2020-01-01T10:00:00.000+0000", "Kauforder", -11.0, "1", "1,00 €")])
    assert tr_core.merge_rows(csv_rows, live) == csv_rows


async def test_bond_mid_prices_use_bid_and_ask():
    from custom_components.traderepublic_insights.pytr_client import bond_mid_prices

    class FakeApi:
        def __init__(self):
            self.queue = []

        async def ticker(self, isin, exchange):
            quotes = {"XS1234567890": {"last": {"price": "10"}, "bid": {"price": "107.5"}, "ask": {"price": "109.5"}}}
            sub_id = str(len(self.queue) + 1)
            self.queue.append((sub_id, {"type": "ticker"}, quotes[isin]))
            return sub_id

        async def recv(self):
            return self.queue.pop(0)

        async def unsubscribe(self, sub_id):
            pass

        async def close(self):
            pass

    positions = [
        {"instrumentId": "XS1234567890", "name": "Aug. 2029", "exchangeIds": ["LSX"], "price": 0.10},
        {"instrumentId": "DE0007500001", "name": "ThyssenKrupp", "exchangeIds": ["LSX"], "price": 15.25},
    ]
    await bond_mid_prices(FakeApi(), positions)
    assert positions[0]["price"] == 1.085
    assert positions[1]["price"] == 15.25


def test_bonds_csv_and_hold_to_maturity(tmp_path):
    from datetime import date
    from pathlib import Path

    rows = tr_core.read_tr_csv(str(Path(__file__).parent / "sample.csv"))
    terms_file = tmp_path / "bonds.csv"
    terms_file.write_text("isin,coupon,maturity,frequency\nXS2322423455,\"1,875\",2031-06-15,1\n", encoding="utf-8")
    terms = tr_core.read_bonds_csv(str(terms_file))
    assert terms == {"XS2322423455": {"coupon": 1.875, "maturity": "2031-06-15", "frequency": 1}}

    res = tr_core.analyze(rows, bond_terms=terms, today=date(2026, 9, 15))
    (bond,) = res["fixed_income"]
    assert bond["coupons_due_count"] == 5
    assert bond["next_coupon"] == "2027-06-15"
    assert bond["status"] == "ok"
    assert bond["profit_to_maturity"] > 0
    assert 2 < bond["return_pa"] < 3

    without = tr_core.analyze(rows, today=date(2026, 9, 15))["fixed_income"][0]
    assert without["profit_to_maturity"] is None
