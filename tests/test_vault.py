"""The option that keeps the PIN out of the config entry."""
import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.finance_insights import fints_client, vault
from custom_components.finance_insights.const import DOMAIN

HERE = Path(__file__).parent
PKG = "custom_components.finance_insights"
REQ = f"{PKG}.config_flow.async_process_requirements"
IBAN = "DE12500500000123456789"


@pytest.fixture(autouse=True)
def _today(freezer):
    freezer.move_to("2026-09-15 12:00:00+02:00")


def _entry(**options):
    return MockConfigEntry(domain=DOMAIN, title="Sparkasse", unique_id="bank", options=options,
                           data={"account_type": "bank", "name": "Sparkasse", "folder": "sparkasse", "use_fints": True,
                                 "blz": "50050000", "login": "u", "pin": "secret", "server": "https://bank.example/fints",
                                 "product_id": "A" * 25, "iban": IBAN})


async def _bank(hass, tmp_path, entry):
    hass.config.config_dir = str(tmp_path)
    (tmp_path / "sparkasse").mkdir(exist_ok=True)
    shutil.copy(HERE / "sparkasse_sample.csv", tmp_path / "sparkasse" / "export.csv")
    entry.add_to_hass(hass)
    with patch(f"{PKG}.async_process_requirements"), patch.object(fints_client, "fetch", return_value={
            "balance": 100.0, "balance_date": None, "transactions": []}):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


def test_the_pin_comes_from_the_entry_or_from_memory(hass):
    stored, asking = _entry(), _entry(ask_pin=True)
    assert vault.pin(hass, stored) == "secret"
    assert vault.pin(hass, asking) is None  # nothing in memory yet
    vault.remember(hass, asking.entry_id, "typed")
    assert vault.pin(hass, asking) == "typed"
    vault.forget(hass, asking.entry_id)
    assert vault.pin(hass, asking) is None


async def test_an_account_without_a_pin_asks_for_one(hass, tmp_path):
    entry = _entry(ask_pin=True)
    entry = await _bank(hass, tmp_path, MockConfigEntry(
        domain=DOMAIN, title="Sparkasse", unique_id="bank", options={"ask_pin": True},
        data={**entry.data, "pin": None}))
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = [f for f in hass.config_entries.flow.async_progress() if f["context"]["source"] == "reauth"]
    assert len(flows) == 1


async def test_the_typed_pin_stays_in_memory_and_is_never_written(hass, tmp_path):
    entry = await _bank(hass, tmp_path, MockConfigEntry(
        domain=DOMAIN, title="Sparkasse", unique_id="bank", options={"ask_pin": True},
        data={**_entry().data, "pin": None}))
    flow = next(f for f in hass.config_entries.flow.async_progress() if f["context"]["source"] == "reauth")

    result = await hass.config_entries.flow.async_configure(flow["flow_id"], {"pin": "1234", "pin_confirm": "9999"})
    assert result["errors"] == {"pin_confirm": "pin_mismatch"}

    with patch(f"{PKG}.async_process_requirements"), patch.object(fints_client, "fetch", return_value={
            "balance": 100.0, "balance_date": None, "transactions": []}):
        result = await hass.config_entries.flow.async_configure(flow["flow_id"], {"pin": "1234", "pin_confirm": "1234"})
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "pin_accepted"
    assert entry.data.get("pin") is None  # the disk never sees it
    assert vault.pin(hass, entry) == "1234"
    assert entry.state is ConfigEntryState.LOADED


async def test_switching_the_option_on_removes_the_stored_pin(hass, tmp_path):
    entry = await _bank(hass, tmp_path, _entry())
    assert entry.data["pin"] == "secret"

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert "ask_pin" in result["data_schema"].schema
    options = {"scan_minutes": 60, "fints_hours": 12, "transfer_keywords": "Trade Republic",
               "offset_rules": "", "ask_pin": True}
    with patch(f"{PKG}.async_process_requirements"), patch.object(fints_client, "fetch", return_value={
            "balance": 100.0, "balance_date": None, "transactions": []}):
        await hass.config_entries.options.async_configure(result["flow_id"], options)
        await hass.async_block_till_done()

    assert "pin" not in entry.data
    assert vault.pin(hass, entry) == "secret"  # carried over, so the account keeps working until the restart
    assert entry.state is ConfigEntryState.LOADED


async def test_diagnostics_contain_no_credentials_and_no_amounts(hass, tmp_path):
    from homeassistant.components.diagnostics import REDACTED

    from custom_components.finance_insights.diagnostics import async_get_config_entry_diagnostics

    entry = await _bank(hass, tmp_path, _entry())
    report = await async_get_config_entry_diagnostics(hass, entry)

    data = report["entry"]["data"]
    assert {data[k] for k in ("pin", "login", "iban", "blz", "product_id", "server")} == {REDACTED}
    assert data["name"] == "Sparkasse" and report["entry"]["type"] == "bank"
    assert report["entry"]["pin_stored_on_disk"] is True
    assert report["sync"]["status"] and "force" not in report["sync"]

    # The analysis is described, never quoted: no amount and no payee reaches the file.
    assert report["result"]["balance"] == {"type": "float", "set": True}
    assert report["result"]["monthly"]["type"] == "list"
    text = str(report)
    assert "secret" not in text and IBAN not in text
    assert not any(isinstance(v, float) for v in report["summary"].values())


def test_every_third_party_package_is_pinned():
    """An exact version cannot be moved to other code, so an update needs a release here."""
    from custom_components.finance_insights.const import FINTS_REQUIREMENTS, PYTR_REQUIREMENTS

    for group, top in ((FINTS_REQUIREMENTS, "fints"), (PYTR_REQUIREMENTS, "pytr")):
        names = [r.split("==")[0].lower().replace("_", "-") for r in group]
        assert all("==" in r for r in group), group
        assert len(set(names)) == len(names)
        assert group[-1].startswith(f"{top}==")  # the package itself installs last

    manifest = json.loads((Path(__file__).parent.parent / "custom_components" / "finance_insights"
                           / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["requirements"] == []  # nothing is installed until a user switches a feature on


def test_the_repository_guard_catches_a_real_product_id_and_iban():
    """A published FinTS product ID can be blocked, and that locks out every legitimate user."""
    from scripts.check_secrets import PATTERNS, is_real_iban

    # Built from parts, so this file itself carries nothing the guard would have to allow.
    real_shape = "ABCDEFGHIJKLMNOPQRSTUVWX" + "1"
    valid_iban = "DE89" + "370400440532013000"

    product_id = PATTERNS["FinTS product ID"]
    assert product_id.findall(f"CONF_PRODUCT_ID = {real_shape}")
    assert not product_id.findall('PID = "ABCDEFGHIJKLMNOPQRSTUVWXY"')  # the placeholder has no digit
    assert PATTERNS["private key"].findall("-----BEGIN OPENSSH " + "PRIVATE KEY-----")
    assert is_real_iban(valid_iban)
    assert not is_real_iban("DE00100123450000000001")  # invented, fails the mod-97 check


def test_the_release_archive_is_what_hacs_installs():
    """A checksum is worth nothing if it covers a file nobody installs."""
    root = Path(__file__).parent.parent
    hacs = json.loads((root / "hacs.json").read_text(encoding="utf-8"))
    workflow = (root / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert hacs["zip_release"] is True
    assert hacs["filename"] == "finance_insights.zip"
    assert hacs["filename"] in workflow and "sha256sum" in workflow
