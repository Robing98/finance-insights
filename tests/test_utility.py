"""Energy and water costs: unit conversion, contracts, forecast, and the entry with a contract subentry."""
from datetime import date, timedelta

import pytest
from homeassistant import config_entries
from homeassistant.components.recorder.models import StatisticMeanType
from homeassistant.components.recorder.statistics import async_import_statistics
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.components.recorder.common import async_wait_recording_done

from custom_components.finance_insights import utility_core
from custom_components.finance_insights.const import DOMAIN

TODAY = date(2026, 9, 15)


@pytest.fixture
def auto_enable_custom_integrations():
    """Replaced per test: the recorder must start before hass."""
    yield


@pytest.fixture
def utility_hass(recorder_mock, enable_custom_integrations, hass):
    return hass
OLD = {"supplier": "Stadtwerke", "start": "2025-03-01", "end": "2026-02-28", "unit_price": 0.35, "base_price": 12.0,
       "advance": 80.0}
NEW = {"supplier": "Check24 Tarif", "start": "2026-03-01", "end": "2027-02-28", "unit_price": 0.28, "base_price": 15.0,
       "advance": 70.0, "bonus": 100.0, "notice_weeks": 4}


def test_units():
    assert utility_core.to_billing_unit(2500, "Wh", "electricity", None) == 2.5
    assert utility_core.to_billing_unit(1500, "L", "water", None) == 1.5
    assert utility_core.to_billing_unit(2, "m³", "gas", 10.5) == 21.0
    assert utility_core.to_billing_unit(2, "m³", "gas", None) is None


def test_contract_switch_forecast_and_settlement():
    # 6 kWh every day for two years.
    daily = {TODAY - timedelta(days=i): 6.0 for i in range(730)}
    res = utility_core.analyze_utility(daily, [OLD, NEW], TODAY, devices={"PC": 30.0, "Fridge": 20.0})
    assert res["cost_today"] == pytest.approx(6 * 0.28 + 15 * 12 / 365, abs=0.01)
    # 1 January to 28 February under the old contract, the rest under the new one.
    old_days, new_days = 31 + 28, (TODAY - date(2026, 3, 1)).days + 1
    expected_year = old_days * (6 * 0.35 + 12 * 12 / 365) + new_days * (6 * 0.28 + 15 * 12 / 365)
    assert res["cost_year"] == pytest.approx(expected_year, abs=0.05)

    period, forecast = res["period"], res["forecast"]
    assert (period["start"], period["end"]) == ("2026-03-01", "2027-02-28")
    assert period["advances_paid"] == 7 * 70 and period["advances_total"] == 12 * 70
    assert forecast["method"] == "last year"
    year_cost = 365 * (6 * 0.28 + 15 * 12 / 365)
    assert forecast["expected_cost"] == pytest.approx(year_cost, abs=0.1)
    assert forecast["settlement"] == pytest.approx(840 - year_cost + 100, abs=0.1)
    assert forecast["suggested_advance"] == pytest.approx((year_cost - 100) / 12, abs=0.01)
    assert period["notice_deadline"] == "2027-01-31" and period["days_to_notice"] == 138
    assert period["last_year_consumption"] == pytest.approx(6 * ((TODAY - date(2026, 3, 1)).days + 1), abs=6.1)
    assert [d["name"] for d in res["devices"]] == ["PC", "Fridge"] and res["devices"][0]["cost"] == pytest.approx(8.4)
    assert len(res["monthly"]) == 13 and res["monthly"][-1]["month"] == "2026-09"


def test_without_history_uses_recent_average_and_without_contract_no_costs():
    daily = {TODAY - timedelta(days=i): 10.0 for i in range(20)}
    res = utility_core.analyze_utility(daily, [NEW], TODAY)
    assert res["forecast"]["method"] == "recent average"
    assert utility_core.analyze_utility(daily, [], TODAY)["cost_month"] is None


async def test_utility_entry_with_contract(utility_hass, tmp_path):
    hass = utility_hass
    hass.config.config_dir = str(tmp_path)
    assert await async_setup_component(hass, "energy", {})
    from homeassistant.components.energy.data import async_get_manager

    manager = await async_get_manager(hass)
    await manager.async_update({"energy_sources": [{"type": "grid", "flow_from": [
        {"stat_energy_from": "sensor.meter", "stat_cost": None, "entity_energy_price": None, "number_energy_price": None}],
        "flow_to": [], "cost_adjustment_day": 0}],
        "device_consumption": [{"stat_consumption": "sensor.pc_energy", "name": "PC"}]})

    now = dt_util.now()
    start = dt_util.start_of_local_day(now.date() - timedelta(days=40))
    stats, total = [], 0.0
    hour = start
    while hour < now - timedelta(hours=1):
        total += 0.25  # 6 kWh per day
        stats.append({"start": dt_util.as_utc(hour), "state": total, "sum": total})
        hour += timedelta(hours=1)
    meta = {"mean_type": StatisticMeanType.NONE, "has_sum": True, "name": "Meter", "source": "recorder",
            "statistic_id": "sensor.meter", "unit_class": "energy", "unit_of_measurement": "kWh"}
    async_import_statistics(hass, meta, stats)
    month_start = dt_util.as_utc(dt_util.start_of_local_day(now.date().replace(day=1)))
    pc_stats = [{"start": month_start, "state": 1000.0, "sum": 0.0},
                {"start": dt_util.as_utc(hour - timedelta(hours=1)), "state": 13000.0, "sum": 12000.0}]
    async_import_statistics(hass, {**meta, "statistic_id": "sensor.pc_energy", "name": "PC", "unit_of_measurement": "Wh"},
                            pc_stats)
    await async_wait_recording_done(hass)

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "utility"})
    schema = {str(k): k for k in result["data_schema"].schema}
    assert schema["statistic"].description == {"suggested_value": "sensor.meter"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"utility": "electricity", "name": "Strom", "statistic": "sensor.meter"})
    await hass.async_block_till_done()
    entry = hass.config_entries.async_get_entry(result["result"].entry_id)
    assert hass.states.get("sensor.strom_cost_month").state == "unknown"

    contract = {"supplier": "Check24 Tarif", "start": (now.date() - timedelta(days=100)).isoformat(),
                "unit_price": 0.30, "base_price": 12.0, "advance": 60.0, "notice_weeks": 4,
                "end": (now.date() + timedelta(days=265)).isoformat()}
    flow = await hass.config_entries.subentries.async_init((entry.entry_id, "contract"), context={"source": "user"})
    bad = await hass.config_entries.subentries.async_configure(flow["flow_id"], {**contract, "end": "2000-01-01"})
    assert bad["errors"] == {"end": "end_before_start"}
    done = await hass.config_entries.subentries.async_configure(bad["flow_id"], contract)
    assert done["type"] == "create_entry"
    await hass.async_block_till_done()

    days = (now.date() - now.date().replace(day=1)).days + 1
    cost_month = float(hass.states.get("sensor.strom_cost_month").state)
    # Today is only partly recorded, so count the imported hours instead of assuming full days.
    kwh_month = 0.25 * sum(1 for row in stats if row["start"] >= month_start)
    assert cost_month == pytest.approx(days * 12 * 12 / 365 + kwh_month * 0.30, abs=0.5)
    assert hass.states.get("sensor.strom_consumption_month").attributes["unit_of_measurement"] == "kWh"
    assert hass.states.get("sensor.strom_notice_deadline").state.startswith(
        (now.date() + timedelta(days=265) - timedelta(weeks=4)).isoformat())
    devices = hass.states.get("sensor.strom_contract_end").attributes["devices"]
    assert devices == [{"name": "PC", "consumption": 12.0, "cost": 3.6}]
    assert hass.states.get("sensor.strom_expected_settlement").state not in ("unknown", "unavailable")

    from homeassistant.helpers.template import Template

    from custom_components.finance_insights.dashboard import build_views, load_templates

    views = {v["path"]: v for v in build_views([entry], load_templates(), {})}
    energy = views["unassigned-costs"]
    used = {c["entity"] for s in energy["sections"] for c in s["cards"] if "entity" in c}
    assert used and all(hass.states.get(e) for e in used), used
    text = "\n".join(Template(c["content"], hass).async_render(parse_result=False)
                     for s in energy["sections"] for c in s["cards"] if c["type"] == "markdown")
    assert "Check24 Tarif" in text and "| PC | 12,0 | 3,60 € |" in text and "Expected refund" in text
    assert [c["heading"] for c in views["unassigned-overview"]["sections"][0]["cards"] if c["type"] == "heading"] == ["Strom"]

    from custom_components.finance_insights.dashboard import load_language

    german = {v["path"]: v for v in build_views([entry], load_templates(), {}, load_language("de"))}
    text = "\n".join(Template(c["content"], hass).async_render(parse_result=False)
                     for s in german["unassigned-costs"]["sections"] for c in s["cards"] if c["type"] == "markdown")
    assert "**Abrechnungsjahr " in text and "Erwartete Erstattung" in text and "| Gerät | Verbrauch | Kosten |" in text
    assert "Strom: Kosten" in str(german["unassigned-costs"])
