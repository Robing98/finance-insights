"""Write the reconstructed history into the Home Assistant statistics.

The charts read statistics, and those begin when the integration was installed. The
exports reach further back, so this fills the gap with one point per day. The series are
external statistics under the `finance_insights:` prefix, so they never collide with the
statistics Home Assistant records for the sensors themselves.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
EUR = "EUR"
# Suffix -> the key in the series and the name shown in the statistics list.
BROKER_SERIES = {"broker_cash": ("cash", "Broker cash"),
                 "contributions": ("contributions", "Net contributions"),
                 "invested_cost": ("cost", "Invested at cost")}
BANK_SERIES = {"bank_balance": ("balance", "Bank balance")}


def statistic_id(prefix: str, suffix: str) -> str:
    return f"{DOMAIN}:{prefix}_{suffix}"


def _metadata(sid: str, name: str) -> dict:
    meta = {"has_sum": False, "name": name, "source": DOMAIN, "statistic_id": sid, "unit_of_measurement": EUR}
    try:
        from homeassistant.components.recorder.models import StatisticMeanType

        meta["mean_type"] = StatisticMeanType.ARITHMETIC
        meta["unit_class"] = None
    except ImportError:  # Home Assistant before the mean_type field
        meta["has_mean"] = True
    return meta


def _start(day: date) -> datetime:
    """Noon local time, cut to the hour. Statistics start on the hour, and noon lands on
    the right day in every time zone, including the ones offset by half an hour."""
    local = datetime.combine(day, time(12), dt_util.get_default_time_zone())
    return dt_util.as_utc(local).replace(minute=0, second=0, microsecond=0)


async def async_write(hass: HomeAssistant, prefix: str, series: list[dict], columns: dict) -> list[str]:
    """Write one statistic per column. Returns the statistic IDs written."""
    if not series or "recorder" not in hass.config.components:
        return []
    from homeassistant.components.recorder.statistics import async_add_external_statistics

    written = []
    for suffix, (key, name) in columns.items():
        points = [{"start": _start(p["date"]), "mean": p[key], "min": p[key], "max": p[key]}
                  for p in series if p.get(key) is not None]
        if not points:
            continue
        sid = statistic_id(prefix, suffix)
        async_add_external_statistics(hass, _metadata(sid, f"{prefix} {name}"), points)
        written.append(sid)
    _LOGGER.debug("Backfilled %d days into %s", len(series), ", ".join(written))
    return written
