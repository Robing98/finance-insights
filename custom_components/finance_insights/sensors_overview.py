"""Sensor descriptions for the overview across all accounts."""
from __future__ import annotations

from homeassistant.components.sensor import SensorStateClass
from homeassistant.const import PERCENTAGE

from .descriptions import FISensorDescription, money

OVERVIEW_SENSORS: tuple[FISensorDescription, ...] = (
    money("net_worth", lambda d: d["net_worth"], "mdi:scale-balance",
          lambda d: {"accounts": d["accounts"], "split": d["split"],
                     "history_statistics": d.get("history_statistics") or []}),
    money("liquid", lambda d: d["liquid"], "mdi:cash"),
    money("invested", lambda d: d["invested"], "mdi:chart-line"),
    money("income_30d", lambda d: d["income_30d"], "mdi:cash-plus"),
    money("spending_30d", lambda d: d["spending_30d"], "mdi:cash-minus"),
    money("income_month", lambda d: d["income_month"], "mdi:cash-plus", lambda d: {"monthly": d["monthly"]}),
    money("spending_month", lambda d: d["spending_month"], "mdi:cash-minus"),
    money("avg_income_12m", lambda d: d["avg_income_12m"], "mdi:cash-multiple"),
    money("avg_spending_12m", lambda d: d["avg_spending_12m"], "mdi:chart-bell-curve-cumulative"),
    money("to_depot_12m", lambda d: d["to_depot_12m"], "mdi:bank-transfer-out"),
    money("saved_12m", lambda d: d["saved_12m"], "mdi:piggy-bank-outline",
          lambda d: d.get("cash_flow") or {}),
    FISensorDescription(key="savings_rate_12m", translation_key="savings_rate_12m", native_unit_of_measurement=PERCENTAGE,
                        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=1, icon="mdi:piggy-bank-outline",
                        value_fn=lambda d: d["savings_rate_12m"]),
)
