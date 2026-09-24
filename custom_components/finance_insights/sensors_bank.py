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
        "total_12m": d["spending_12m"], "avg_month_12m": d["avg_spending_12m"], "months_covered": d["months_12m"]}


def _income_attrs(d: dict) -> dict:
    # `monthly` is here as well as on the spending sensor, so the income cards read one entity.
    return {"kinds_12m": d["income_kinds_12m"], "total_12m": d["income_12m"], "last_salary": d["last_salary"],
            "payers_12m": d["payers_12m"], "monthly": d["monthly"], "months_covered": d["months_12m"],
            "avg_month_12m": d["avg_income_12m"], "by_year": d["by_year"]}


BANK_SENSORS: tuple[FISensorDescription, ...] = (
    money("balance", lambda d: d["balance"], "mdi:bank", _balance_attrs),
    money("income_30d", lambda d: d["income_30d"], "mdi:cash-plus"),
    money("income_prev_30d", lambda d: d["income_prev_30d"], "mdi:calendar-arrow-left"),
    money("spending_30d", lambda d: d["spending_30d"], "mdi:cash-minus"),
    money("spending_prev_30d", lambda d: d["spending_prev_30d"], "mdi:calendar-arrow-left"),
    money("income_month", lambda d: d["income_month"], "mdi:cash-plus", _income_attrs),
    money("income_prev_month", lambda d: d["income_prev_month"], "mdi:cash-plus"),
    money("avg_income_12m", lambda d: d["avg_income_12m"], "mdi:cash-multiple"),
    money("spending_month", lambda d: d["spending_month"], "mdi:cash-minus", _spending_attrs),
    money("spending_prev_month", lambda d: d["spending_prev_month"], "mdi:cash-minus"),
    money("avg_spending_12m", lambda d: d["avg_spending_12m"], "mdi:chart-bell-curve-cumulative"),
    money("fixed_costs_month", lambda d: d["fixed_costs_month"], "mdi:calendar-sync", lambda d: {"recurring": d["recurring"]}),
    money("to_depot_12m", lambda d: d["to_depot_12m"], "mdi:bank-transfer-out"),
    money("forecast_low", lambda d: (d.get("forecast") or {}).get("low"), "mdi:chart-timeline-variant-shimmer",
          lambda d: d.get("forecast") or {}),
    money("forecast_end", lambda d: (d.get("forecast") or {}).get("end"), "mdi:calendar-arrow-right"),
    money("last_salary", lambda d: (d["last_salary"] or {}).get("amount"), "mdi:briefcase-outline",
          lambda d: d["last_salary"] or {}),
    money("saved_12m", lambda d: d["saved_12m"], "mdi:piggy-bank-outline"),
    FISensorDescription(key="savings_rate_12m", translation_key="savings_rate_12m", native_unit_of_measurement=PERCENTAGE,
                        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=1, icon="mdi:piggy-bank-outline",
                        value_fn=lambda d: d["savings_rate_12m"]),
    FISensorDescription(key="last_transaction", translation_key="last_transaction", device_class=SensorDeviceClass.TIMESTAMP,
                        icon="mdi:clock-outline", value_fn=lambda d: _ts(d["last_date"])),
)


# ---------------------------------------------------------------- business account

def _biz(d: dict) -> dict:
    return d.get("business") or {}


def _period(key: str, field: str):
    def value(d: dict):
        return (_biz(d).get(key) or {}).get(field)
    return value


def _vat_attrs(d: dict) -> dict:
    b = _biz(d)
    return {"quarters": b.get("quarters", [])[-8:], "months": b.get("months", [])[-24:],
            "small_business": b.get("small_business", False), "rates": b.get("rates", {})}


def _year_attrs(d: dict) -> dict:
    b = _biz(d)
    return {"years": b.get("years", []), "quarters": b.get("quarters", [])[-8:], **(b.get("year") or {})}


def _open_attrs(d: dict) -> dict:
    b = _biz(d)
    return {"items": b.get("unassigned_items", []), "income": (b.get("year") or {}).get("unassigned_income"),
            "expense": (b.get("year") or {}).get("unassigned_expense")}


BUSINESS_SENSORS: tuple[FISensorDescription, ...] = (
    money("business_revenue_net", _period("year", "revenue_net"), "mdi:receipt-text-outline", _year_attrs),
    money("business_expenses_net", _period("year", "expenses_net"), "mdi:receipt-text-minus-outline"),
    money("business_profit", _period("year", "profit"), "mdi:chart-line-variant"),
    money("business_vat_due_month", _period("month", "vat_due"), "mdi:percent-outline", _vat_attrs),
    money("business_vat_due_quarter", _period("quarter", "vat_due"), "mdi:calendar-range"),
    money("business_reserve", lambda d: _biz(d).get("reserve"), "mdi:piggy-bank-outline",
          lambda d: {"percent": _biz(d).get("reserve_pct")}),
    money("business_unassigned", _period("year", "unassigned"), "mdi:help-circle-outline", _open_attrs),
)
