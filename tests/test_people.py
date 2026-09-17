"""Several people: owners, overviews per person or household, and the generated dashboard."""
import shutil
from datetime import timedelta
from pathlib import Path

import pytest
from homeassistant import config_entries
from homeassistant.exceptions import ServiceValidationError
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.finance_insights.const import DOMAIN
from custom_components.finance_insights.coordinator import entity_prefix

HERE = Path(__file__).parent
URL = "dashboard-finances"


@pytest.fixture(autouse=True)
def _today(freezer):
    freezer.move_to("2026-09-15 12:00:00+02:00")


def _entry(kind, title, owner=None, uid=None, shared=None, members=None, **data):
    options = {}
    if owner:
        options["owner"] = owner
    if shared:
        options["shared_with"] = shared
    if members is not None:
        options["members"] = members
    return MockConfigEntry(domain=DOMAIN, title=title, unique_id=uid or title, options=options,
                           data={"account_type": kind, **data})


def _tr(tmp_path, title, folder, owner):
    (tmp_path / folder).mkdir(exist_ok=True)
    shutil.copy(HERE / "sample.csv", tmp_path / folder / "export.csv")
    return _entry("trade_republic", title, owner, folder=folder, use_pytr=False)


def _bank(tmp_path, title, folder, owner, **options):
    (tmp_path / folder).mkdir(exist_ok=True)
    shutil.copy(HERE / "sparkasse_sample.csv", tmp_path / folder / "export.csv")
    entry = _entry("bank", title, owner, name=title, folder=folder, use_fints=False)
    return MockConfigEntry(domain=DOMAIN, title=title, unique_id=title, data=entry.data,
                           options={**entry.options, **options})


async def _setup(hass, *entries):
    for e in entries:
        e.add_to_hass(hass)
        assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done()


def _value(hass, entity_id):
    return float(hass.states.get(entity_id).state)


def test_entity_prefixes():
    cases = {("trade_republic", "Trade Republic"): "trade_republic",
             ("trade_republic", "Trade Republic Anna"): "trade_republic_anna",
             ("trade_republic", "Anna"): "trade_republic_anna",
             ("overview", "Finance overview"): "finance_overview",
             ("overview", "Anna und Ben"): "finance_overview_anna_und_ben",
             ("bank", "Sparkasse Ben"): "sparkasse_ben"}
    for (kind, title), prefix in cases.items():
        assert entity_prefix(_entry(kind, title)) == prefix


async def test_accounts_per_person_and_household(hass, tmp_path):
    hass.config.config_dir = str(tmp_path)
    anna = await hass.auth.async_create_user("Anna")
    ben = await hass.auth.async_create_user("Ben")
    await _setup(hass,
                 _tr(tmp_path, "Trade Republic", "tr_anna", anna.id),
                 _tr(tmp_path, "Trade Republic Ben", "tr_ben", ben.id),
                 _bank(tmp_path, "Sparkasse Anna", "spk_anna", anna.id, transfer_keywords=""),
                 _bank(tmp_path, "Sparkasse Ben", "spk_ben", None, transfer_keywords=""),
                 _entry("overview", "Anna", uid="o1", members=[anna.id]),
                 _entry("overview", "Ben", uid="o2", members=[ben.id]),
                 _entry("overview", "Haushalt", uid="o3", members=[anna.id, ben.id]),
                 _entry("overview", "Finance overview", uid="overview"))

    tr_anna, tr_ben = _value(hass, "sensor.trade_republic_net_worth"), _value(hass, "sensor.trade_republic_ben_net_worth")
    holdings = [s for s in hass.states.async_all("sensor") if s.attributes.get("trade_republic_holding") == "trade_republic_ben"]
    assert len(holdings) == 6 and all(s.entity_id.startswith("sensor.trade_republic_ben_") for s in holdings)

    # Transfers only match accounts of the same person; "Sparkasse Ben" has no owner.
    assert hass.states.get("sensor.sparkasse_anna_data_status").attributes["matched_transfers"] > 0
    assert hass.states.get("sensor.sparkasse_ben_data_status").attributes["matched_transfers"] == 0

    assert hass.states.get("sensor.sparkasse_anna_balance").state == "unknown"
    assert _value(hass, "sensor.finance_overview_anna_net_worth") == pytest.approx(tr_anna, abs=0.02)
    assert _value(hass, "sensor.finance_overview_ben_net_worth") == pytest.approx(tr_ben, abs=0.02)
    assert _value(hass, "sensor.finance_overview_haushalt_net_worth") == pytest.approx(tr_anna + tr_ben, abs=0.02)
    names = {a["name"] for a in hass.states.get("sensor.finance_overview_net_worth").attributes["accounts"]}
    assert names == {"Trade Republic", "Trade Republic Ben", "Sparkasse Anna", "Sparkasse Ben"}


async def test_flows_set_owner_and_members(hass, tmp_path):
    hass.config.config_dir = str(tmp_path)
    anna = await hass.auth.async_create_user("Anna")
    ctx = {"source": config_entries.SOURCE_USER, "user_id": anna.id}
    result = await hass.config_entries.flow.async_init(DOMAIN, context=ctx)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "trade_republic"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"name": "Anna", "folder": " ", "use_pytr": False})
    assert result["errors"] == {"folder": "folder_invalid"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"name": "Anna", "folder": "tr_anna", "use_pytr": False})
    await hass.async_block_till_done()
    assert result["title"] == "Anna" and result["options"] == {"owner": anna.id}

    for name in ("Paar", "Paar"):
        result = await hass.config_entries.flow.async_init(DOMAIN, context=ctx)
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "overview"})
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"name": name, "members": [anna.id]})
    assert result["type"] == "abort" and result["reason"] == "already_configured"

    overview = next(e for e in hass.config_entries.async_entries(DOMAIN) if e.title == "Paar")
    assert overview.options == {"members": [anna.id]}
    result = await hass.config_entries.options.async_init(overview.entry_id)
    assert set(result["data_schema"].schema) == {"members"}


async def test_build_dashboard(hass, tmp_path, hass_ws_client):
    hass.config.config_dir = str(tmp_path)
    assert await async_setup_component(hass, "lovelace", {})
    anna = await hass.auth.async_create_user("Anna")
    ben = await hass.auth.async_create_user("Ben")
    await _setup(hass,
                 _tr(tmp_path, "Trade Republic", "tr_anna", anna.id),
                 _tr(tmp_path, "Trade Republic Ben", "tr_ben", ben.id),
                 _entry("overview", "Haushalt", uid="o3", members=[anna.id, ben.id]))

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "build_dashboard", {"dashboard": URL}, blocking=True, return_response=True)

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "lovelace/dashboards/create", "url_path": URL, "title": "Finances"})
    assert (await client.receive_json())["success"]
    response = await hass.services.async_call(DOMAIN, "build_dashboard", {"dashboard": URL}, blocking=True,
                                              return_response=True)
    from homeassistant.components.lovelace.const import LOVELACE_DATA

    config = await hass.data[LOVELACE_DATA].dashboards[URL].async_load(False)
    views = {v["path"]: v for v in config["views"]}
    assert response == {"views": 9}
    assert list(views)[0] == "finance-overview-haushalt-overview"
    assert views["trade-republic-depot"]["visible"] == [{"user": anna.id}]
    ben_depot = views["trade-republic-ben-depot"]
    assert ben_depot["title"] == "Trade Republic Ben: Depot" and ben_depot["visible"] == [{"user": ben.id}]
    text = str(ben_depot)
    assert "sensor.trade_republic_ben_net_worth" in text and "sensor.trade_republic_net_worth" not in text
    assert "'eq', 'trade_republic_ben'" in text
    assert views["finance-overview-haushalt-overview"]["visible"] == [{"user": anna.id}, {"user": ben.id}]

    # Sharing an account adds the user to its views after the automatic rebuild.
    entry = next(e for e in hass.config_entries.async_entries(DOMAIN) if e.title == "Trade Republic Ben")
    hass.config_entries.async_update_entry(entry, options={**entry.options, "shared_with": [anna.id]})
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=10))
    await hass.async_block_till_done()
    config = await hass.data[LOVELACE_DATA].dashboards[URL].async_load(False)
    ben_depot = next(v for v in config["views"] if v["path"] == "trade-republic-ben-depot")
    assert ben_depot["visible"] == [{"user": ben.id}, {"user": anna.id}]
