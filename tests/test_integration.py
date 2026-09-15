import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.traderepublic_insights import pytr_client
from custom_components.traderepublic_insights.const import DOMAIN

SAMPLE = Path(__file__).parent / "sample.csv"
REQ = "custom_components.traderepublic_insights.config_flow.async_process_requirements"


async def test_csv_flow_creates_entry(hass, tmp_path):
    hass.config.config_dir = str(tmp_path)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    with patch("custom_components.traderepublic_insights.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"folder": "trade_republic", "use_pytr": False})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert (tmp_path / "trade_republic").is_dir()


async def test_pytr_flow_push_confirmation(hass, tmp_path):
    hass.config.config_dir = str(tmp_path)
    api = MagicMock()
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"folder": "tr", "use_pytr": True})
    assert result["step_id"] == "pytr"
    with patch(REQ), patch.object(pytr_client, "start_login", return_value=(api, False)):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"phone": "+49 151 1234567", "pin": "1234"})
    assert result["step_id"] == "pytr_confirm"
    with patch.object(pytr_client, "finish_login", side_effect=pytr_client.PytrNotConfirmed):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["errors"] == {"base": "not_confirmed"}
    with patch.object(pytr_client, "finish_login"), \
         patch("custom_components.traderepublic_insights.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["phone"] == "+491511234567"


async def test_sensors_from_csv(hass, tmp_path):
    hass.config.config_dir = str(tmp_path)
    (tmp_path / "trade_republic").mkdir()
    shutil.copy(SAMPLE, tmp_path / "trade_republic" / "export.csv")
    entry = MockConfigEntry(domain=DOMAIN, data={"folder": "trade_republic", "use_pytr": False}, unique_id="x")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    states = {s.entity_id: s for s in hass.states.async_all("sensor")}
    net = states["sensor.trade_republic_net_worth"]
    assert float(net.state) > 0
    assert net.attributes["unit_of_measurement"] == "EUR"
    holdings = [s for s in states.values() if s.attributes.get("trade_republic_holding")]
    assert len(holdings) == 6
    assert states["sensor.trade_republic_data_status"].state == "disabled"
    assert hass.states.get("button.trade_republic_refresh") is not None


async def test_live_prices_and_reauth(hass, tmp_path):
    hass.config.config_dir = str(tmp_path)
    (tmp_path / "tr").mkdir()
    shutil.copy(SAMPLE, tmp_path / "tr" / "export.csv")
    entry = MockConfigEntry(domain=DOMAIN, unique_id="y",
                            data={"folder": "tr", "use_pytr": True, "phone": "+491", "pin": "1"})
    entry.add_to_hass(hass)
    live = dict(positions=[dict(isin="CH0038863350", name="Nestle", shares=6.0, avg_cost=91.67, price=140.0)],
                cash=1000.0, timeline_updated=True)
    with patch("custom_components.traderepublic_insights.async_process_requirements"), \
         patch.object(pytr_client, "fetch", return_value=live), \
         patch("custom_components.traderepublic_insights.tr_core.rows_from_pytr", return_value=[]):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    ares = next(s for s in hass.states.async_all("sensor") if s.attributes.get("symbol") == "CH0038863350")
    assert ares.attributes["price_source"] == "live"
    assert float(ares.state) == 840.0
    assert float(hass.states.get("sensor.trade_republic_cash").state) == 1000.0
    assert hass.states.get("sensor.trade_republic_data_status").state == "ok"

    coordinator = entry.runtime_data
    with patch.object(pytr_client, "fetch", side_effect=pytr_client.PytrAuthError), \
         patch("custom_components.traderepublic_insights.tr_core.rows_from_pytr", return_value=[]):
        await coordinator.async_refresh()
        await hass.async_block_till_done()
    assert hass.states.get("sensor.trade_republic_data_status").state == "login_required"
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert any(f["context"]["source"] == "reauth" for f in flows)


async def test_dashboard_templates_render(hass, tmp_path):
    import yaml
    from homeassistant.helpers.template import Template

    hass.config.config_dir = str(tmp_path)
    (tmp_path / "trade_republic").mkdir()
    shutil.copy(SAMPLE, tmp_path / "trade_republic" / "export.csv")
    entry = MockConfigEntry(domain=DOMAIN, data={"folder": "trade_republic", "use_pytr": False}, unique_id="z")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    dash = yaml.safe_load((Path(__file__).parents[1] / "dashboards" / "depot.yaml").read_text())
    used = set()
    outputs = []
    for section in dash["views"][0]["sections"]:
        for card in section["cards"]:
            used.update(e if isinstance(e, str) else e["entity"] for e in card.get("entities", []))
            if "entity" in card:
                used.add(card["entity"])
            if card["type"] == "markdown":
                outputs.append(Template(card["content"], hass).async_render(parse_result=False))
    missing = [e for e in used if hass.states.get(e) is None]
    assert not missing, missing
    table = outputs[0].splitlines()
    assert table[0].startswith("| Position") and len(table) == 2 + 6 and "Dividends" in table[0]
    bonds = next(o for o in outputs if o.startswith("| Bond"))
    assert "VOLKSWAGEN" in bonds
    print("\n".join(outputs))
