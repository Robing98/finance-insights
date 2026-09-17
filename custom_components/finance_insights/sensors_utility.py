"""Sensor descriptions for energy and water costs."""
from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.util import dt as dt_util

from .descriptions import FISensorDescription, money


def _period(d: dict) -> dict:
    return d.get("period") or {}


def _forecast(d: dict) -> dict:
    return d.get("forecast") or {}


def _ts(value: str | None):
    if not value:
        return None
    return dt_util.as_utc(datetime.fromisoformat(value).replace(tzinfo=dt_util.get_default_time_zone()))


def _consumption(key: str, field: str, icon: str) -> FISensorDescription:
    # The unit follows the contract's billing unit, set by the sensor entity.
    return FISensorDescription(key=key, translation_key=key, state_class=SensorStateClass.TOTAL,
                               suggested_display_precision=2, icon=icon, value_fn=lambda d, f=field: d.get(f))


UTILITY_SENSORS: tuple[FISensorDescription, ...] = (
    money("cost_today", lambda d: d.get("cost_today"), "mdi:cash-clock"),
    money("cost_month", lambda d: d.get("cost_month"), "mdi:calendar-month", lambda d: {"monthly": d.get("monthly")}),
    money("cost_year", lambda d: d.get("cost_year"), "mdi:calendar-range"),
    money("expected_period_cost", lambda d: _forecast(d).get("expected_cost"), "mdi:crystal-ball",
          lambda d: {**_forecast(d), **{f"period_{k}": v for k, v in _period(d).items()}}),
    money("expected_settlement", lambda d: _forecast(d).get("settlement"), "mdi:scale-balance",
          lambda d: {"meaning": "positive: refund, negative: extra payment", "method": _forecast(d).get("method")}),
    money("suggested_advance", lambda d: _forecast(d).get("suggested_advance"), "mdi:cash-sync",
          lambda d: {"current_advance": _period(d).get("advance")}),
    _consumption("consumption_month", "consumption_month", "mdi:meter-electric-outline"),
    FISensorDescription(key="contract_end", translation_key="contract_end", device_class=SensorDeviceClass.TIMESTAMP,
                        icon="mdi:file-sign", value_fn=lambda d: _ts(_period(d).get("contract_end")),
                        attrs_fn=lambda d: {"supplier": _period(d).get("supplier"), "contracts": d.get("contracts"),
                                            "devices": d.get("devices")}),
    FISensorDescription(key="notice_deadline", translation_key="notice_deadline", device_class=SensorDeviceClass.TIMESTAMP,
                        icon="mdi:calendar-alert", value_fn=lambda d: _ts(_period(d).get("notice_deadline")),
                        attrs_fn=lambda d: {"days_left": _period(d).get("days_to_notice")}),
)
