"""Coordinators for Trade Republic accounts, bank accounts, and the overview."""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from . import bank_core, fints_client, overview_core, pytr_client, tr_core
from .const import (
    BALANCE_FILE, BONDS_FILE, CONF_ACCOUNT_TYPE, CONF_BLZ, CONF_FINTS_HOURS, CONF_FOLDER, CONF_IBAN, CONF_LOGIN,
    CONF_MEMBERS, CONF_NAME, CONF_OFFSET_RULES, CONF_OWNER, CONF_PHONE, CONF_PIN, CONF_PRODUCT_ID, CONF_SCAN_MINUTES, CONF_SERVER, CONF_TIMELINE_HOURS,
    CONF_TRANSFER_KEYWORDS, CONF_USE_FINTS, CONF_USE_PYTR, DEFAULT_FINTS_HOURS, DEFAULT_SCAN_MINUTES,
    DEFAULT_TIMELINE_HOURS, DOMAIN, FINTS_STATE_DIR, LEGACY_DOMAIN, PRICES_FILE, PYTR_DIR, RULES_FILE,
    DEFAULT_OVERVIEW_TITLE, DEFAULT_TR_TITLE, TYPE_BANK, TYPE_OVERVIEW, TYPE_TRADE_REPUBLIC,
)

_LOGGER = logging.getLogger(__name__)


def _digest(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:12]


def cookies_path(hass: HomeAssistant, phone: str, domain: str = DOMAIN) -> Path:
    return Path(hass.config.path(".storage", f"{domain}_cookies_{_digest(phone)}.txt"))


def fints_state_path(hass: HomeAssistant, blz: str, login: str) -> Path:
    return Path(hass.config.path(".storage", FINTS_STATE_DIR, f"{_digest(blz, login)}.bin"))


def entity_prefix(entry: ConfigEntry) -> str:
    """Entity ID prefix. Default titles keep the prefixes of earlier versions."""
    kind, title = account_type(entry), entry.title
    if kind == TYPE_TRADE_REPUBLIC:
        rest = re.sub(r"^\s*trade\s*republic\s*", "", title, flags=re.IGNORECASE) if title != DEFAULT_TR_TITLE else ""
        return f"trade_republic_{slugify(rest)}" if slugify(rest) else "trade_republic"
    if kind == TYPE_OVERVIEW:
        return "finance_overview" if title == DEFAULT_OVERVIEW_TITLE else f"finance_overview_{slugify(title)}"
    return slugify(title)


def owner_of(entry: ConfigEntry) -> str | None:
    return entry.options.get(CONF_OWNER)


def parse_keywords(text: str | None) -> list[str]:
    if text is None:
        return list(bank_core.DEFAULT_TRANSFER_KEYWORDS)
    return [k.strip() for k in re.split(r"[,\n;]", text) if k.strip()]


@dataclass
class SyncState:
    status: str = "disabled"
    last_sync: str | None = None
    force: bool = False
    auth_failed: bool = False


class FinanceHub:
    """Knows every account so transfers between them can be matched."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.coordinators: dict[str, FIBaseCoordinator] = {}
        self._unsubs: dict[str, callable] = {}

    @callback
    def register(self, coordinator: FIBaseCoordinator) -> None:
        entry_id = coordinator.config_entry.entry_id
        self.coordinators[entry_id] = coordinator
        self._unsubs[entry_id] = coordinator.async_add_listener(lambda: self._changed(coordinator))

    @callback
    def unregister(self, entry_id: str) -> None:
        self.coordinators.pop(entry_id, None)
        if unsub := self._unsubs.pop(entry_id, None):
            unsub()
        self._recompute(TYPE_TRADE_REPUBLIC)

    def of_type(self, kind: str) -> list:
        return [c for c in self.coordinators.values() if c.kind == kind and c.data is not None]

    def same_owner(self, kind: str, owner: str | None) -> list:
        """Transfers are only matched between accounts of the same person."""
        return [c for c in self.of_type(kind) if owner_of(c.config_entry) == owner]

    def broker_flows(self, owner: str | None = None) -> list[dict]:
        flows = []
        for c in self.same_owner(TYPE_TRADE_REPUBLIC, owner):
            for r in c.rows:
                if r["bucket"] in ("deposit", "withdrawal"):
                    flows.append({"id": r["id"], "date": date.fromisoformat(r["date"]), "amount": r["cash"]})
        return flows

    def bank_ibans(self, owner: str | None = None) -> set[str]:
        ibans: set[str] = set()
        for c in self.coordinators.values():
            if c.kind == TYPE_BANK and owner_of(c.config_entry) == owner:
                ibans.update(r["account"] for r in c.raw_rows if r["account"])
        return ibans

    @callback
    def _changed(self, coordinator: FIBaseCoordinator) -> None:
        if coordinator.recomputing:
            return
        self._recompute(coordinator.kind, coordinator)

    @callback
    def _recompute(self, kind: str, source: FIBaseCoordinator | None = None) -> None:
        if kind in (TYPE_TRADE_REPUBLIC, TYPE_BANK):
            for c in self.coordinators.values():
                if c is not source and c.kind == TYPE_BANK and c.data is not None and c.raw_rows:
                    c.async_recompute()
        for c in self.coordinators.values():
            if c.kind == TYPE_OVERVIEW:
                c.async_recompute()


class FIBaseCoordinator(DataUpdateCoordinator[dict]):
    config_entry: ConfigEntry
    kind: str = ""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, hub: FinanceHub, interval: timedelta | None) -> None:
        super().__init__(hass, _LOGGER, name=f"{DOMAIN}_{entry.entry_id}", config_entry=entry, update_interval=interval)
        self.hub = hub
        self.recomputing = False
        self.sync = SyncState()

    @property
    def device_name(self) -> str:
        return self.config_entry.title

    @property
    def entity_prefix(self) -> str:
        return entity_prefix(self.config_entry)

    @callback
    def async_recompute(self) -> None:
        """Recompute from cached data without fetching, e.g. after another account changed."""


# ---------------------------------------------------------------- Trade Republic

class TRCoordinator(FIBaseCoordinator):
    kind = TYPE_TRADE_REPUBLIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, hub: FinanceHub) -> None:
        minutes = entry.options.get(CONF_SCAN_MINUTES, DEFAULT_SCAN_MINUTES)
        super().__init__(hass, entry, hub, timedelta(minutes=minutes))
        self.folder = Path(hass.config.path(entry.data[CONF_FOLDER]))
        self.use_pytr = entry.data.get(CONF_USE_PYTR, False)
        self.sync.status = "idle" if self.use_pytr else "disabled"
        self.rows: list[dict] = []
        self._last_tl = None

    def _timeline_due(self) -> bool:
        hours = self.config_entry.options.get(CONF_TIMELINE_HOURS, DEFAULT_TIMELINE_HOURS)
        return self.sync.force or self._last_tl is None or dt_util.utcnow() - self._last_tl >= timedelta(hours=hours)

    def _newest_csv(self) -> Path | None:
        files = [p for p in self.folder.glob("*.csv") if p.name not in (PRICES_FILE, BONDS_FILE)]
        return max(files, key=lambda p: p.stat().st_mtime) if files else None

    def _refresh(self, with_timeline: bool) -> dict:
        self.folder.mkdir(parents=True, exist_ok=True)
        csv_file = self._newest_csv()
        csv_rows = tr_core.read_tr_csv(str(csv_file)) if csv_file else []
        prices_file = self.folder / PRICES_FILE
        prices = tr_core.read_prices_csv(str(prices_file)) if prices_file.exists() else {}
        bonds_file = self.folder / BONDS_FILE
        bond_terms = tr_core.read_bonds_csv(str(bonds_file)) if bonds_file.exists() else {}

        live, status, auth_failed = None, "disabled", False
        if self.use_pytr:
            data = self.config_entry.data
            try:
                live = pytr_client.fetch(
                    data[CONF_PHONE], data[CONF_PIN], cookies_path(self.hass, data[CONF_PHONE]),
                    self.folder / PYTR_DIR, csv_rows[-1]["datetime"] if csv_rows else None, with_timeline)
                status = "ok"
            except pytr_client.PytrAuthError:
                status, auth_failed = "login_required", True
            except ImportError:
                status = "pytr_missing"
            except Exception as err:  # noqa: BLE001 - keep CSV data flowing when the API breaks
                _LOGGER.warning("pytr sync failed, using CSV data only: %s", err)
                status = f"error: {type(err).__name__}"

        live_rows = []
        if self.use_pytr:
            try:
                live_rows = tr_core.rows_from_pytr(pytr_client.load_events(self.folder / PYTR_DIR))
            except ImportError:
                live_rows = []
        rows = tr_core.merge_rows(csv_rows, live_rows)
        if not rows:
            raise UpdateFailed(f"No Trade Republic CSV export found in {self.folder}")
        result = tr_core.analyze(rows, prices, live_positions=live["positions"] if live else None,
                                 live_cash=live["cash"] if live else None, today=dt_util.now().date(),
                                 bond_terms=bond_terms)
        result["meta"] = dict(csv_file=csv_file.name if csv_file else None, csv_rows=len(csv_rows),
                              timeline_rows=len(rows) - len(csv_rows), prices_file=prices_file.exists(),
                              live_prices=bool(live), timeline_updated=bool(live and live.get("timeline_updated")))
        return dict(result=result, rows=rows, status=status, auth_failed=auth_failed)

    async def _async_update_data(self) -> dict:
        with_tl = self.use_pytr and self._timeline_due()
        try:
            out = await self.hass.async_add_executor_job(self._refresh, with_tl)
        except UpdateFailed:
            raise
        except (OSError, ValueError, KeyError) as err:
            raise UpdateFailed(f"Could not read Trade Republic data: {err}") from err
        self.rows = out["rows"]
        self.sync.status = out["status"]
        if out["result"]["meta"]["timeline_updated"]:
            self._last_tl = dt_util.utcnow()
            self.sync.last_sync = self._last_tl.isoformat()
            self.sync.force = False
        if out["auth_failed"] and not self.sync.auth_failed:
            self.config_entry.async_start_reauth(self.hass)
        self.sync.auth_failed = out["auth_failed"]
        return out["result"]


# ---------------------------------------------------------------- Bank

def _rows_to_json(rows: list[dict]) -> list[dict]:
    return [{**r, "date": r["date"].isoformat(), "value_date": r["value_date"].isoformat()
             if hasattr(r["value_date"], "isoformat") else str(r["value_date"])} for r in rows]


def _rows_from_json(items: list[dict]) -> list[dict]:
    out = []
    for r in items:
        d = bank_core.parse_date(r["date"])
        out.append({**r, "date": d, "value_date": bank_core.parse_date(str(r.get("value_date"))) or d})
    return out


class BankCoordinator(FIBaseCoordinator):
    kind = TYPE_BANK

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, hub: FinanceHub) -> None:
        minutes = entry.options.get(CONF_SCAN_MINUTES, DEFAULT_SCAN_MINUTES)
        super().__init__(hass, entry, hub, timedelta(minutes=minutes))
        self.folder = Path(hass.config.path(entry.data[CONF_FOLDER]))
        self.use_fints = entry.data.get(CONF_USE_FINTS, False)
        self.sync.status = "idle" if self.use_fints else "disabled"
        self.raw_rows: list[dict] = []
        self.live_balances: dict[str, float] = {}
        self.anchors: dict = {}
        self.rules: list = []
        self.meta: dict = {}
        self._last_fints = None

    def _fints_due(self) -> bool:
        hours = self.config_entry.options.get(CONF_FINTS_HOURS, DEFAULT_FINTS_HOURS)
        return self.sync.force or self._last_fints is None or dt_util.utcnow() - self._last_fints >= timedelta(hours=hours)

    def _refresh(self, with_fints: bool) -> dict:
        self.folder.mkdir(parents=True, exist_ok=True)
        skip = {BALANCE_FILE, RULES_FILE}
        files = sorted(p for p in self.folder.glob("*.csv") if p.name not in skip)
        exports, errors = [], []
        for p in files:
            try:
                exports.append(bank_core.read_sparkasse_csv(p.read_bytes()))
            except ValueError as err:
                errors.append(f"{p.name}: {err}")
        csv_rows = bank_core.merge_exports(exports)
        balance_file, rules_file = self.folder / BALANCE_FILE, self.folder / RULES_FILE
        anchors = bank_core.read_balance_csv(balance_file.read_bytes()) if balance_file.exists() else {}
        rules = bank_core.read_rules_csv(rules_file.read_bytes()) if rules_file.exists() else []

        cache_file = self.folder / ".fints_cache.json"
        cached = _rows_from_json(json.loads(cache_file.read_text(encoding="utf-8"))) if cache_file.exists() else []
        status, auth_failed, live = ("disabled" if not self.use_fints else self.sync.status), False, None
        if self.use_fints and with_fints:
            d = self.config_entry.data
            try:
                live = fints_client.fetch(d[CONF_BLZ], d[CONF_LOGIN], d[CONF_PIN], d[CONF_SERVER], d[CONF_PRODUCT_ID],
                                          fints_state_path(self.hass, d[CONF_BLZ], d[CONF_LOGIN]), d[CONF_IBAN])
                fresh = bank_core.rows_from_fints(d[CONF_IBAN], live["transactions"])
                by_id = {r["id"]: r for r in cached}
                by_id.update({r["id"]: r for r in fresh})
                cached = sorted(by_id.values(), key=lambda r: (r["date"], r["amount"]))
                cache_file.write_text(json.dumps(_rows_to_json(cached)), encoding="utf-8")
                status = "ok"
            except fints_client.FinTSAuthRequired:
                status, auth_failed = "tan_required", True
            except ImportError:
                status = "fints_missing"
            except Exception as err:  # noqa: BLE001 - keep CSV data flowing when the bank refuses
                _LOGGER.warning("FinTS sync failed, using CSV data only: %s", err)
                status = f"error: {type(err).__name__}"

        newest_csv = max((r["date"] for r in csv_rows), default=None)
        rows = csv_rows + [r for r in cached if newest_csv is None or r["date"] > newest_csv]
        rows.sort(key=lambda r: (r["date"], r["amount"]))
        if not rows:
            raise UpdateFailed(f"No bank CSV export found in {self.folder}")
        return dict(rows=rows, anchors=anchors, rules=rules, live=live, status=status, auth_failed=auth_failed,
                    meta=dict(csv_files=[p.name for p in files], csv_rows=len(csv_rows), fints_rows=len(rows) - len(csv_rows),
                              balance_file=balance_file.exists(), rules_file=rules_file.exists(), errors=errors))

    def _compute(self) -> dict:
        owner = owner_of(self.config_entry)
        own = self.hub.bank_ibans(owner) | {r["account"] for r in self.raw_rows if r["account"]}
        matched, _ = bank_core.match_transfers(self.raw_rows, self.hub.broker_flows(owner))
        keywords = parse_keywords(self.config_entry.options.get(CONF_TRANSFER_KEYWORDS))
        classified = bank_core.classify(self.raw_rows, own_ibans=own, keywords=keywords, matched_ids=matched,
                                        user_rules=self.rules,
                                        offset_rules=bank_core.parse_offset_rules(self.config_entry.options.get(CONF_OFFSET_RULES)))
        result = bank_core.analyze_bank(classified, dt_util.now().date(), balances=self.live_balances,
                                        balance_anchors=self.anchors)
        result["meta"] = {**self.meta, "matched_transfers": len(matched)}
        return result

    async def _async_update_data(self) -> dict:
        with_fints = self.use_fints and self._fints_due()
        try:
            out = await self.hass.async_add_executor_job(self._refresh, with_fints)
        except UpdateFailed:
            raise
        except (OSError, ValueError, KeyError) as err:
            raise UpdateFailed(f"Could not read bank data: {err}") from err
        self.raw_rows, self.anchors, self.rules, self.meta = out["rows"], out["anchors"], out["rules"], out["meta"]
        if out["live"] and out["live"].get("balance") is not None:
            self.live_balances = {self.config_entry.data[CONF_IBAN]: out["live"]["balance"]}
        self.sync.status = out["status"]
        if with_fints and out["status"] == "ok":
            self._last_fints = dt_util.utcnow()
            self.sync.last_sync = self._last_fints.isoformat()
            self.sync.force = False
        if out["auth_failed"] and not self.sync.auth_failed:
            self.config_entry.async_start_reauth(self.hass)
        self.sync.auth_failed = out["auth_failed"]
        return self._compute()

    @callback
    def async_recompute(self) -> None:
        self.recomputing = True
        try:
            self.async_set_updated_data(self._compute())
        finally:
            self.recomputing = False


# ---------------------------------------------------------------- Overview

class OverviewCoordinator(FIBaseCoordinator):
    kind = TYPE_OVERVIEW

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, hub: FinanceHub) -> None:
        super().__init__(hass, entry, hub, None)
        self.sync.status = "ok"

    def _included(self, kind: str) -> list:
        """No members: every account. Otherwise the accounts owned by the members."""
        members = self.config_entry.options.get(CONF_MEMBERS) or []
        return [c for c in self.hub.of_type(kind) if not members or owner_of(c.config_entry) in members]

    def _compute(self) -> dict:
        banks = [(c.device_name, c.data) for c in self._included(TYPE_BANK)]
        brokers = [(c.device_name, c.data) for c in self._included(TYPE_TRADE_REPUBLIC)]
        return overview_core.build_overview(banks, brokers, dt_util.now().date())

    async def _async_update_data(self) -> dict:
        return self._compute()

    @callback
    def async_recompute(self) -> None:
        self.recomputing = True
        try:
            self.async_set_updated_data(self._compute())
        finally:
            self.recomputing = False


COORDINATORS = {TYPE_TRADE_REPUBLIC: TRCoordinator, TYPE_BANK: BankCoordinator, TYPE_OVERVIEW: OverviewCoordinator}


def legacy_cookies_path(hass: HomeAssistant, phone: str) -> Path:
    return cookies_path(hass, phone, LEGACY_DOMAIN)


def account_type(entry: ConfigEntry) -> str:
    return entry.data.get(CONF_ACCOUNT_TYPE, TYPE_TRADE_REPUBLIC)


__all__ = ["COORDINATORS", "FinanceHub", "account_type", "entity_prefix", "owner_of", "CONF_NAME"]
