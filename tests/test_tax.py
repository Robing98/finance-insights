"""Capital income tax estimates."""
from datetime import date

import pytest

from custom_components.finance_insights import tax_core, tr_core

HEAD = ('"datetime","date","account_type","category","type","asset_class","name","symbol","shares","price",'
        '"amount","fee","tax","currency","original_amount","original_currency","fx_rate","description",'
        '"transaction_id","counterparty_name","counterparty_iban","payment_reference","mcc_code"\n')


def _row(day, category, kind, cls, name, symbol, shares, price, amount, tax=""):
    return (f'"{day}T09:00:00.000Z","{day}","DEFAULT","{category}","{kind}","{cls}","{name}","{symbol}",'
            f'"{shares}","{price}","{amount}","","{tax}","EUR","","","","","{day}{symbol}{kind}","","","",""\n')


CSV = HEAD + "".join([
    _row("2025-01-10", "TRADING", "BUY", "STOCK", "Alpha", "DE000A", 10, 100, -1000),
    _row("2025-02-01", "TRADING", "BUY", "FUND", "World ETF", "IE000F", 10, 100, -1000),
    _row("2025-06-10", "TRADING", "SELL", "STOCK", "Alpha", "DE000A", -10, 80, 800),
    _row("2025-10-01", "TRADING", "BUY", "CRYPTO", "Bitcoin", "XF000BTC", 1, 1000, -1000),
    _row("2026-01-05", "TRADING", "BUY", "CRYPTO", "Ether", "XF000ETH", 0.5, 1000, -500),
    _row("2026-02-05", "TRADING", "SELL", "CRYPTO", "Ether", "XF000ETH", -0.5, 1400, 700),
    _row("2026-03-01", "CASH", "DIVIDEND", "STOCK", "Beta", "DE000B", 5, "", 300, -45),
    _row("2026-04-01", "CASH", "INTEREST_PAYMENT", "", "", "", "", "", 30),
])
TODAY = date(2026, 9, 22)


def _analyze(**kw):
    rows = tr_core.read_tr_csv(CSV)
    ledger = tr_core.Ledger().run(rows)
    hold = tr_core.holdings(ledger, {"IE000F": 150.0, "XF000BTC": 1200.0})
    return tax_core.analyze_tax(rows, hold, TODAY, **kw)


def test_income_tax_tariff():
    assert tax_core.income_tax(12348, 2026) == 0
    assert tax_core.income_tax(20000, 2026) == 1570
    assert tax_core.income_tax(12096, 2025) == 0
    assert tax_core.income_tax(40000, 2026, joint=True) == 2 * tax_core.income_tax(20000, 2026)
    assert tax_core.tariff_year(2031) == 2026
    assert tax_core.flat_rate(0) == pytest.approx(0.26375)
    assert tax_core.flat_rate(0.09) == pytest.approx(1.145 / 4.09)


def test_allowance_pots_and_reset():
    t = _analyze()
    # 300 dividend + 30 interest; the stock loss from 2025 stays in the stock pot.
    assert t["taxable_expected"] == pytest.approx(330)
    assert t["loss_pot_stock"] == pytest.approx(200)
    assert t["history"][0]["loss_pot_stock"] == pytest.approx(200)
    assert t["allowance_left"] == pytest.approx(670)
    assert t["withheld_ytd"] == pytest.approx(45)
    # The ETF gain is 70 % taxable: 10 shares x 50 EUR x 0.7 = 350, less than the room left.
    etf = t["reset"][0]
    assert etf["symbol"] == "IE000F" and etf["shares"] == 10 and etf["taxable_gain"] == pytest.approx(350)
    assert etf["covers"] is False
    codes = [x["code"] for x in t["tips"]]
    assert codes[:3] == ["enter_income", "reset", "stock_pot"]
    assert "crypto_free" in codes and "vorabpauschale" not in codes


def test_reset_stops_at_the_allowance():
    t = _analyze(allowance=100)
    # 330 taxable against a 100 EUR Freistellungsauftrag: nothing left, tax expected on the rest.
    assert t["allowance_left"] == 0 and t["reset"] == []
    assert t["tax_expected"] == pytest.approx(230 * 0.26375, abs=0.01)
    assert {"code": "fsa", "amount": 100.0, "limit": 1000.0} in t["tips"]


def test_crypto_holding_period_and_private_sales():
    t = _analyze()
    assert t["private_sales_ytd"] == pytest.approx(200)
    btc = t["crypto"][0]
    assert btc["taxable_shares"] == 1 and btc["next_tax_free"] == "2026-10-02"
    tip = next(x for x in t["tips"] if x["code"] == "crypto_limit")
    assert tip["over"] is False


def test_guenstigerpruefung_and_nv():
    low = _analyze(other_income=3000)
    assert low["personal"]["nv_possible"] is True
    assert low["tips"][0]["code"] == "nv"
    # With more capital income and a small other income, the personal rate beats 25 %.
    rows = tr_core.read_tr_csv(CSV + _row("2026-05-01", "CASH", "DIVIDEND", "STOCK", "Beta", "DE000B", 5, "", 6000, -1300))
    hold = tr_core.holdings(tr_core.Ledger().run(rows), {"IE000F": 150.0})
    t = tax_core.analyze_tax(rows, hold, TODAY, other_income=10000)
    p = t["personal"]
    assert p["taxable_capital"] == pytest.approx(5330)
    assert p["nv_possible"] is False
    assert p["personal_tax"] < p["flat_tax"] and p["saving"] > 100
    assert t["tips"][0]["code"] == "guenstiger"
