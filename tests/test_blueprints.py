"""The automation blueprints load and react to the integration's events."""
import shutil
from pathlib import Path

import pytest
from homeassistant.components.blueprint import models
from homeassistant.components.blueprint.schemas import BLUEPRINT_SCHEMA
from homeassistant.core import callback
from homeassistant.setup import async_setup_component
from homeassistant.util.yaml import load_yaml

SOURCE = Path(__file__).parent.parent / "blueprints" / "automation" / "finance_insights"


@pytest.mark.parametrize("path", sorted(SOURCE.glob("*.yaml")), ids=lambda p: p.name)
def test_blueprint_is_valid(path):
    bp = models.Blueprint(load_yaml(path), expected_domain="automation", schema=BLUEPRINT_SCHEMA)
    assert bp.metadata["source_url"].endswith(path.name)


async def _automation(hass, tmp_path, name, inputs):
    hass.config.config_dir = str(tmp_path)
    target = tmp_path / "blueprints" / "automation" / "finance_insights"
    target.mkdir(parents=True)
    shutil.copy(SOURCE / name, target / name)
    done = []
    hass.bus.async_listen("fi_test", callback(lambda e: done.append(e.data["msg"])))
    actions = [{"event": "fi_test", "event_data": {"msg": "{{ name }} {{ amount }}"}}]
    assert await async_setup_component(hass, "automation", {"automation": {
        "use_blueprint": {"path": f"finance_insights/{name}", "input": {**inputs, "actions": actions}}}})
    await hass.async_block_till_done()
    return done


async def test_new_booking_filters_direction_and_amount(hass, tmp_path):
    done = await _automation(hass, tmp_path, "new_booking.yaml", {"direction": "out", "min_amount": 50})
    for amount in (-12.99, 80.0, -120.0):
        hass.bus.async_fire("finance_insights_transaction", {"entry_id": "x", "account": "Giro", "name": "SHOP",
                                                              "amount": amount, "category": "", "date": "2026-09-15"})
    await hass.async_block_till_done()
    assert done == ["SHOP -120.0"]


async def test_salary_blueprint(hass, tmp_path):
    done = await _automation(hass, tmp_path, "salary.yaml", {})
    hass.bus.async_fire("finance_insights_transaction", {"entry_id": "x", "account": "Giro", "name": "MUSTER GMBH",
                                                          "amount": 2100.0, "category": "Salary", "date": "2026-09-28"})
    hass.bus.async_fire("finance_insights_transaction", {"entry_id": "x", "account": "Giro", "name": "REWE",
                                                          "amount": -20.0, "category": "Groceries", "date": "2026-09-28"})
    await hass.async_block_till_done()
    assert done == ["MUSTER GMBH 2100.0"]
