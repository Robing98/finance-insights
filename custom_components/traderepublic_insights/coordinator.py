"""Data coordinator: reads the CSV folder, optionally syncs via pytr, runs the analysis."""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from . import pytr_client, tr_core
from .const import (
    CONF_FOLDER, CONF_PHONE, CONF_PIN, CONF_SCAN_MINUTES, CONF_TIMELINE_HOURS, CONF_USE_PYTR,
    DEFAULT_SCAN_MINUTES, DEFAULT_TIMELINE_HOURS, DOMAIN, BONDS_FILE, PRICES_FILE, PYTR_DIR,
)

_LOGGER = logging.getLogger(__name__)


def cookies_path(hass: HomeAssistant, phone: str) -> Path:
    digest = hashlib.sha256(phone.encode()).hexdigest()[:12]
    return Path(hass.config.path(".storage", f"{DOMAIN}_cookies_{digest}.txt"))


@dataclass
class SyncState:
    status: str = "disabled"
    last_timeline_sync: str | None = None
    force_timeline: bool = False
    auth_failed: bool = False


class TRCoordinator(DataUpdateCoordinator[dict]):
    """Refreshes on an interval; the pytr timeline has its own, longer interval."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        minutes = entry.options.get(CONF_SCAN_MINUTES, DEFAULT_SCAN_MINUTES)
        super().__init__(hass, _LOGGER, name=DOMAIN, config_entry=entry,
                         update_interval=timedelta(minutes=minutes))
        self.folder = Path(hass.config.path(entry.data[CONF_FOLDER]))
        self.use_pytr = entry.data.get(CONF_USE_PYTR, False)
        self.sync = SyncState(status="idle" if self.use_pytr else "disabled")
        self._last_tl = None

    def _timeline_due(self) -> bool:
        hours = self.config_entry.options.get(CONF_TIMELINE_HOURS, DEFAULT_TIMELINE_HOURS)
        return (self.sync.force_timeline or self._last_tl is None
                or dt_util.utcnow() - self._last_tl >= timedelta(hours=hours))

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

        live = None
        status = "disabled"
        auth_failed = False
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

        result = tr_core.analyze(
            rows, prices,
            live_positions=live["positions"] if live else None,
            live_cash=live["cash"] if live else None,
            today=dt_util.now().date(),
            bond_terms=bond_terms,
        )
        result["meta"] = dict(
            csv_file=csv_file.name if csv_file else None,
            csv_rows=len(csv_rows), timeline_rows=len(rows) - len(csv_rows),
            prices_file=prices_file.exists(), live_prices=bool(live),
            timeline_updated=bool(live and live.get("timeline_updated")),
        )
        return dict(result=result, status=status, auth_failed=auth_failed)

    async def _async_update_data(self) -> dict:
        with_tl = self.use_pytr and self._timeline_due()
        try:
            out = await self.hass.async_add_executor_job(self._refresh, with_tl)
        except UpdateFailed:
            raise
        except (OSError, ValueError, KeyError) as err:
            raise UpdateFailed(f"Could not read Trade Republic data: {err}") from err

        self.sync.status = out["status"]
        if out["result"]["meta"]["timeline_updated"]:
            self._last_tl = dt_util.utcnow()
            self.sync.last_timeline_sync = self._last_tl.isoformat()
            self.sync.force_timeline = False
        if out["auth_failed"] and not self.sync.auth_failed:
            self.config_entry.async_start_reauth(self.hass)
        self.sync.auth_failed = out["auth_failed"]
        return out["result"]
