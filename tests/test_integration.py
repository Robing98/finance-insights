import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.finance_insights import fints_client, pytr_client
from custom_components.finance_insights.const import DOMAIN, LEGACY_DOMAIN

HERE = Path(__file__).parent
TR_SAMPLE = HERE / "sample.csv"
SPK_SAMPLE = HERE / "sparkasse_sample.csv"
PKG = "custom_components.finance_insights"
REQ = f"{PKG}.config_flow.async_process_requirements"
IBAN = "DE12500500000123456789"


@pytest.fixture(autouse=True)
def _today(freezer):
    freezer.move_to("2026-09-15 12:00:00+02:00")


def _copy(tmp_path, sample, folder, name="export.csv"):
    (tmp_path / folder).mkdir(exist_ok=True)
    shutil.copy(sample, tmp_path / folder / name)


async def _setup(hass, entry):
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _tr_entry(**data):
    return MockConfigEntry(domain=DOMAIN, title="Trade Republic", unique_id="tr",
                           data={"account_type": "trade_republic", "folder": "trade_republic", "use_pytr": False, **data})


def _bank_entry(options=None, **data):
    return MockConfigEntry(domain=DOMAIN, title="Sparkasse", unique_id="bank", options=options or {},
                           data={"account_type": "bank", "name": "Sparkasse", "folder": "sparkasse", "use_fints": False, **data})


async def _menu(hass, choice):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.MENU
    return await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": choice})


# ---------------------------------------------------------------- config flows

async def test_menu_and_trade_republic_csv_flow(hass, tmp_path):
    hass.config.config_dir = str(tmp_path)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["menu_options"] == ["trade_republic", "bank", "utility", "overview"]
    result = await _menu(hass, "trade_republic")
    with patch(f"{PKG}.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"name": "Trade Republic", "folder": "trade_republic", "use_pytr": False})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["account_type"] == "trade_republic"
    assert (tmp_path / "trade_republic").is_dir()


async def test_pytr_flow_push_confirmation(hass, tmp_path):
    hass.config.config_dir = str(tmp_path)
    result = await _menu(hass, "trade_republic")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"name": "Trade Republic", "folder": "tr", "use_pytr": True})
    assert result["step_id"] == "pytr"
    with patch(REQ), patch.object(pytr_client, "start_login", return_value=(MagicMock(), False)):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"phone": "+49 151 1234567", "pin": "1234"})
    assert result["step_id"] == "pytr_confirm"
    with patch.object(pytr_client, "finish_login", side_effect=pytr_client.PytrNotConfirmed):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["errors"] == {"base": "not_confirmed"}
    with patch.object(pytr_client, "finish_login"), patch(f"{PKG}.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["phone"] == "+491511234567"


async def test_bank_csv_flow(hass, tmp_path):
    hass.config.config_dir = str(tmp_path)
    result = await _menu(hass, "bank")
    with patch(f"{PKG}.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"name": "Sparkasse", "folder": "sparkasse", "use_fints": False})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Sparkasse"
    assert result["data"] == {"account_type": "bank", "name": "Sparkasse", "folder": "sparkasse", "use_fints": False}


async def test_fints_flow_with_push_tan(hass, tmp_path):
    hass.config.config_dir = str(tmp_path)
    result = await _menu(hass, "bank")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Giro", "folder": "giro", "use_fints": True})
    assert result["step_id"] == "fints"
    form = {"blz": "5005000", "server": "https://banking.example/fints", "login": "user1", "pin": "secret", "product_id": "PID"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], form)
    assert result["errors"] == {"blz": "blz_format"}

    session = SimpleNamespace(decoupled=True, challenge_text="Bitte bestätigen Sie in der S-pushTAN-App")
    with patch(REQ), patch.object(fints_client, "start_login", return_value=session) as start:
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {**form, "blz": "50050000"})
    assert start.call_args.args[:5] == ("50050000", "user1", "secret", "https://banking.example/fints", "PID")
    assert result["step_id"] == "fints_tan"
    assert "S-pushTAN" in result["description_placeholders"]["challenge"]
    with patch.object(fints_client, "finish_login", side_effect=fints_client.FinTSNotConfirmed):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["errors"] == {"base": "not_confirmed"}
    with patch.object(fints_client, "finish_login", return_value=[IBAN, "DE99500500000000000001"]):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "fints_account"
    with patch(f"{PKG}.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"iban": IBAN})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["iban"] == IBAN and result["data"]["product_id"] == "PID"


async def test_import_legacy_keeps_entity_ids(hass, tmp_path):
    hass.config.config_dir = str(tmp_path)
    _copy(tmp_path, TR_SAMPLE, "trade_republic")
    old = MockConfigEntry(domain=LEGACY_DOMAIN, title="Trade Republic", unique_id="old",
                          data={"folder": "trade_republic", "use_pytr": False}, options={"scan_minutes": 15})
    old.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["menu_options"][0] == "import_legacy"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "import_legacy"})
    assert result["description_placeholders"] == {"folder": "trade_republic"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"] == {"scan_minutes": 15}
    assert not hass.config_entries.async_entries(LEGACY_DOMAIN)
    assert hass.states.get("sensor.trade_republic_net_worth") is not None


async def test_bank_options(hass, tmp_path):
    hass.config.config_dir = str(tmp_path)
    _copy(tmp_path, SPK_SAMPLE, "sparkasse")
    entry = _bank_entry()
    await _setup(hass, entry)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert set(result["data_schema"].schema) == {"owner", "shared_with", "scan_minutes", "fints_hours", "transfer_keywords", "offset_rules"}
    before = float(hass.states.get("sensor.sparkasse_avg_spending_12m").state)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"scan_minutes": 60, "fints_hours": 12, "transfer_keywords": "Trade Republic, Scalable",
                            "offset_rules": "Muster GmbH => Rent and housing"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    # The salary now offsets the rent, so average spending drops and no income is left.
    assert float(hass.states.get("sensor.sparkasse_avg_spending_12m").state) < before
    assert float(hass.states.get("sensor.sparkasse_avg_income_12m").state) == 0


# ---------------------------------------------------------------- sensors

async def test_trade_republic_sensors_from_csv(hass, tmp_path):
    hass.config.config_dir = str(tmp_path)
    _copy(tmp_path, TR_SAMPLE, "trade_republic")
    await _setup(hass, _tr_entry())
    states = {s.entity_id: s for s in hass.states.async_all("sensor")}
    net = states["sensor.trade_republic_net_worth"]
    assert float(net.state) > 0
    assert net.attributes["unit_of_measurement"] == "EUR"
    assert len([s for s in states.values() if s.attributes.get("trade_republic_holding")]) == 6
    assert states["sensor.trade_republic_data_status"].state == "disabled"
    assert hass.states.get("button.trade_republic_refresh") is not None


async def test_live_prices_and_reauth(hass, tmp_path):
    hass.config.config_dir = str(tmp_path)
    _copy(tmp_path, TR_SAMPLE, "tr")
    entry = _tr_entry(folder="tr", use_pytr=True, phone="+491", pin="1")
    live = dict(positions=[dict(isin="CH0038863350", name="Nestle", shares=6.0, avg_cost=91.67, price=140.0)],
                cash=1000.0, timeline_updated=True)
    with patch(f"{PKG}.async_process_requirements"), patch.object(pytr_client, "fetch", return_value=live), \
         patch(f"{PKG}.tr_core.rows_from_pytr", return_value=[]):
        await _setup(hass, entry)
    holding = next(s for s in hass.states.async_all("sensor") if s.attributes.get("symbol") == "CH0038863350")
    assert holding.attributes["price_source"] == "live" and float(holding.state) == 840.0
    assert float(hass.states.get("sensor.trade_republic_cash").state) == 1000.0
    assert hass.states.get("sensor.trade_republic_data_status").state == "ok"

    with patch.object(pytr_client, "fetch", side_effect=pytr_client.PytrAuthError), \
         patch(f"{PKG}.tr_core.rows_from_pytr", return_value=[]):
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
    assert hass.states.get("sensor.trade_republic_data_status").state == "login_required"
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert any(f["context"]["source"] == "reauth" for f in flows)


async def test_bank_tr_and_overview_together(hass, tmp_path):
    hass.config.config_dir = str(tmp_path)
    _copy(tmp_path, SPK_SAMPLE, "sparkasse")
    (tmp_path / "sparkasse" / "balance.csv").write_text(f"iban;date;balance\n{IBAN};15.09.2026;2.500,00\n")
    _copy(tmp_path, TR_SAMPLE, "trade_republic")
    # No keyword rule: transfers to Trade Republic must be found by amount and date alone.
    bank = _bank_entry(options={"transfer_keywords": ""})
    await _setup(hass, bank)
    status = hass.states.get("sensor.sparkasse_data_status")
    assert status.attributes["matched_transfers"] == 0
    await _setup(hass, _tr_entry())
    assert hass.states.get("sensor.sparkasse_data_status").attributes["matched_transfers"] > 0
    assert float(hass.states.get("sensor.sparkasse_to_depot_12m").state) >= 5000.0
    assert float(hass.states.get("sensor.sparkasse_balance").state) == 2500.0

    overview = MockConfigEntry(domain=DOMAIN, title="Finance overview", unique_id="overview", data={"account_type": "overview"})
    await _setup(hass, overview)
    net = hass.states.get("sensor.finance_overview_net_worth")
    tr_net = float(hass.states.get("sensor.trade_republic_net_worth").state)
    assert float(net.state) == pytest.approx(2500.0 + tr_net, abs=0.02)
    assert {a["name"] for a in net.attributes["accounts"]} == {"Sparkasse", "Trade Republic"}
    assert hass.states.get("sensor.finance_overview_data_status") is None

    spending = hass.states.get("sensor.sparkasse_spending_month")
    assert len(spending.attributes["monthly"]) == 24
    assert hass.states.get("sensor.sparkasse_fixed_costs_month").attributes["recurring"]

    await hass.config_entries.async_unload(bank.entry_id)
    await hass.async_block_till_done()
    assert float(hass.states.get("sensor.finance_overview_net_worth").state) == pytest.approx(tr_net, abs=0.02)


async def test_fints_sync_and_tan_required(hass, tmp_path):
    hass.config.config_dir = str(tmp_path)
    _copy(tmp_path, SPK_SAMPLE, "sparkasse")
    entry = _bank_entry(use_fints=True, blz="50050000", login="u", pin="p", server="https://x", product_id="PID", iban=IBAN)
    tx = [SimpleNamespace(data={"date": __import__("datetime").date(2026, 9, 14), "amount": SimpleNamespace(amount=-42.0),
                                "applicant_name": "REWE MARKT", "purpose": "Kartenzahlung", "posting_text": "KARTENZAHLUNG"})]
    with patch(f"{PKG}.async_process_requirements"), \
         patch.object(fints_client, "fetch", return_value={"balance": 1234.56, "balance_date": None, "transactions": tx}):
        await _setup(hass, entry)
    assert hass.states.get("sensor.sparkasse_data_status").state == "ok"
    assert float(hass.states.get("sensor.sparkasse_balance").state) == 1234.56
    assert hass.states.get("sensor.sparkasse_data_status").attributes["fints_rows"] == 1

    entry.runtime_data.sync.force = True
    with patch.object(fints_client, "fetch", side_effect=fints_client.FinTSAuthRequired):
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
    assert hass.states.get("sensor.sparkasse_data_status").state == "tan_required"
    assert any(f["context"]["source"] == "reauth" for f in hass.config_entries.flow.async_progress_by_handler(DOMAIN))


async def test_fints_reauth_updates_pin(hass, tmp_path):
    hass.config.config_dir = str(tmp_path)
    _copy(tmp_path, SPK_SAMPLE, "sparkasse")
    entry = _bank_entry(use_fints=True, blz="50050000", login="u", pin="old", server="https://x", product_id="PID", iban=IBAN)
    with patch(f"{PKG}.async_process_requirements"), patch.object(fints_client, "fetch", side_effect=fints_client.FinTSAuthRequired):
        await _setup(hass, entry)
    flow = next(f for f in hass.config_entries.flow.async_progress_by_handler(DOMAIN) if f["context"]["source"] == "reauth")
    session = SimpleNamespace(decoupled=False, challenge_text="TAN für Login")
    with patch(REQ), patch.object(fints_client, "start_login", return_value=session):
        result = await hass.config_entries.flow.async_configure(flow["flow_id"], {"pin": "new"})
    assert result["step_id"] == "fints_tan_code"
    with patch.object(fints_client, "finish_login", return_value=[IBAN]), patch(f"{PKG}.async_process_requirements"), \
         patch.object(fints_client, "fetch", return_value={"balance": 1.0, "balance_date": None, "transactions": []}):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"tan": "123456"})
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "reauth_successful"
    assert entry.data["pin"] == "new"


def _render_tabs(hass, entries):
    from homeassistant.helpers.template import Template

    from custom_components.finance_insights.dashboard import build_views, load_templates

    views = build_views(entries, load_templates(), {})
    used, rendered = set(), {}
    for view in views:
        texts = []
        for section in view["sections"]:
            for card in section["cards"]:
                used.update(e if isinstance(e, str) else e["entity"] for e in card.get("entities", []))
                used.update(s["entity"] for s in card.get("series", []))
                if "entity" in card:
                    used.add(card["entity"])
                if card["type"] == "markdown":
                    texts.append(Template(card["content"], hass).async_render(parse_result=False))
        rendered[view["path"]] = "\n".join(texts)
    missing = [e for e in used if hass.states.get(e) is None]
    assert not missing, missing
    return views, rendered


async def test_dashboards_render(hass, tmp_path):
    hass.config.config_dir = str(tmp_path)
    _copy(tmp_path, TR_SAMPLE, "trade_republic")
    _copy(tmp_path, SPK_SAMPLE, "sparkasse")
    await _setup(hass, _tr_entry())
    await _setup(hass, _bank_entry())
    await _setup(hass, MockConfigEntry(domain=DOMAIN, title="Finance overview", unique_id="ov", data={"account_type": "overview"}))

    views, rendered = _render_tabs(hass, hass.config_entries.async_entries(DOMAIN))
    assert [v["path"] for v in views] == [
        "unassigned-overview", "unassigned-portfolio", "unassigned-bonds", "unassigned-dividends", "unassigned-spending",
        "unassigned-costs", "unassigned-income", "unassigned-charts", "unassigned-data", "household-finance-overview"]
    table = rendered["unassigned-portfolio"].splitlines()
    assert table[0].startswith("| Position") and len(table) >= 2 + 6
    assert "VOLKSWAGEN" in rendered["unassigned-bonds"]
    assert "| Trade Republic | Broker |" in rendered["household-finance-overview"]
    assert "| Hausverwaltung Beispiel | Rent and housing | monthly | 650,00 € |" in rendered["unassigned-costs"]
    assert "No balance yet" in rendered["unassigned-data"]


async def test_dashboard_in_german(hass, tmp_path):
    import re

    from homeassistant.helpers.template import Template

    from custom_components.finance_insights.dashboard import build_views, load_language, load_templates

    hass.config.config_dir = str(tmp_path)
    _copy(tmp_path, TR_SAMPLE, "trade_republic")
    _copy(tmp_path, SPK_SAMPLE, "sparkasse")
    await _setup(hass, _tr_entry())
    await _setup(hass, _bank_entry())
    await _setup(hass, MockConfigEntry(domain=DOMAIN, title="Finance overview", unique_id="ov", data={"account_type": "overview"}))

    catalog = load_language("de")
    entries = hass.config_entries.async_entries(DOMAIN)
    english = {v["path"]: v for v in build_views(entries, load_templates(), {})}
    views = {v["path"]: v for v in build_views(entries, load_templates(), {}, catalog)}
    assert list(views) == list(english)  # same paths, so switching the language keeps edited tabs apart
    assert [v["title"] for v in views.values()][:6] == ["Übersicht", "Portfolio", "Anleihen", "Dividenden", "Ausgaben",
                                                        "Laufende Kosten"]
    assert views["unassigned-overview"]["title"] == "Übersicht"
    assert views["unassigned-costs"]["sections"][0]["cards"][0]["heading"] == "Sparkasse: Fixkosten"

    # Every English phrase of the catalog occurs in the templates, so nothing is left untranslated by a typo.
    source = str(load_templates())
    unused = [en for en, _ in catalog["phrases"] if en not in source]
    assert not unused, unused
    rendered = {}
    for path, view in views.items():
        texts = [Template(c["content"], hass).async_render(parse_result=False)
                 for s in view["sections"] for c in s["cards"] if c["type"] == "markdown"]
        rendered[path] = "\n".join(texts)
        for card in (c for s in view["sections"] for c in s["cards"]):
            for series in card.get("series", []):
                assert series["name"] in catalog["strings"].values() or series["name"] == "Shopping", series["name"]
    costs = rendered["unassigned-costs"]
    assert "| Hausverwaltung Beispiel | Miete und Wohnen | monatlich | 650,00 € |" in costs
    assert re.search(r"\| \d\d\.\d\d\.\d{4} \|\n", costs)
    assert "**Diesen Monat**" in rendered["unassigned-spending"]
    assert "Noch kein Kontostand" in rendered["unassigned-data"]
    assert "| Konto | Art | Kontostand | Investiert |" in rendered["household-finance-overview"]
