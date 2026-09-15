"""Sensor descriptions for a bank account (Sparkasse CSV or FinTS)."""
from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import PERCENTAGE
from homeassistant.util import dt as dt_util

from .descriptions import FISensorDescription, money


def _ts(value: str | None):
    if not value:
        return None
    return dt_util.as_utc(datetime.fromisoformat(value).replace(tzinfo=dt_util.get_default_time_zone()))


def _balance_attrs(d: dict) -> dict:
    return {"source": d["balance_source"], "history": d["balance_history"], "pending_amount": d["pending_amount"],
            "accounts": d["accounts"]}


def _spending_attrs(d: dict) -> dict:
    return {k: d[k] for k in ("monthly", "groups_12m", "categories_12m", "merchants_12m", "merchants_month", "by_year")} | {
        "total_12m": d["spending_12m"], "avg_month_12m": d["avg_spending_12m"]}


def _income_attrs(d: dict) -> dict:
    return {"kinds_12m": d["income_kinds_12m"], "total_12m": d["income_12m"], "last_salary": d["last_salary"]}


BANK_SENSORS: tuple[FISensorDescription, ...] = (
    money("balance", lambda d: d["balance"], "mdi:bank", _balance_attrs),
    money("income_month", lambda d: d["income_month"], "mdi:cash-plus", _income_attrs),
    money("income_prev_month", lambda d: d["income_prev_month"], "mdi:cash-plus"),
    money("avg_income_12m", lambda d: d["avg_income_12m"], "mdi:cash-multiple"),
    money("spending_month", lambda d: d["spending_month"], "mdi:cash-minus", _spending_attrs),
    money("spending_prev_month", lambda d: d["spending_prev_month"], "mdi:cash-minus"),
    money("avg_spending_12m", lambda d: d["avg_spending_12m"], "mdi:chart-bell-curve-cumulative"),
    money("fixed_costs_month", lambda d: d["fixed_costs_month"], "mdi:calendar-sync", lambda d: {"recurring": d["recurring"]}),
    money("to_depot_12m", lambda d: d["to_depot_12m"], "mdi:bank-transfer-out"),
    money("last_salary", lambda d: (d["last_salary"] or {}).get("amount"), "mdi:briefcase-outline",
          lambda d: d["last_salary"] or {}),
    FISensorDescription(key="savings_rate_12m", translation_key="savings_rate_12m", native_unit_of_measurement=PERCENTAGE,
                        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=1, icon="mdi:piggy-bank-outline",
                        value_fn=lambda d: d["savings_rate_12m"]),
    FISensorDescription(key="last_transaction", translation_key="last_transaction", device_class=SensorDeviceClass.TIMESTAMP,
                        icon="mdi:clock-outline", value_fn=lambda d: _ts(d["last_date"])),
)
