"""Sensor descriptions for a Trade Republic account."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import PERCENTAGE
from homeassistant.util import dt as dt_util

from .descriptions import EUR, FISensorDescription

def _money(key: str, field: str | None = None, attrs=None, icon: str | None = None, **kw) -> FISensorDescription:
    return FISensorDescription(
        key=key, translation_key=key, native_unit_of_measurement=EUR,
        device_class=SensorDeviceClass.MONETARY, state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2, icon=icon,
        value_fn=lambda d, f=field or key: d["summary"][f], attrs_fn=attrs, **kw,
    )


def _allocation(d: dict) -> dict:
    by = defaultdict(float)
    for h in d["holdings"]:
        by[h["asset_class"]] += h["value"] or 0
    return {"allocation": {k: round(v, 2) for k, v in sorted(by.items(), key=lambda kv: -kv[1])}}


def _income_attrs(d: dict) -> dict:
    year = str(dt_util.now().year)
    return {"by_kind": {k: round(v, 2) for k, v in d["income_by_year_kind"].get(year, {}).items()}}


def _spending_attrs(d: dict) -> dict:
    month = dt_util.now().strftime("%Y-%m")
    by = defaultdict(float)
    for s in d["spending"]:
        if s["month"] == month:
            by[s["category"]] += s["value"]
    return {"by_category": {k: round(v, 2) for k, v in sorted(by.items(), key=lambda kv: -kv[1])},
            "last_12_months": {m["month"]: round(m["spending"], 2) for m in d["monthly"][-12:]}}


SPENDING_GROUPS = {
    "Food and drink": {"Groceries", "Bakeries", "Restaurants", "Bars", "Fast food", "Liquor stores"},
    "Shopping": {"Clothing", "Online and misc. retail", "Department stores", "General merchandise", "Books",
                 "Electronics", "Hobby and toys", "Sports", "Beauty", "Pharmacy"},
    "Home": {"Home and furniture", "Utilities", "Phone and internet"},
    "Subscriptions": {"Software and subscriptions", "Streaming and media", "Digital goods", "Games"},
    "Transport and travel": {"Transport", "Travel", "Fuel", "Direct debits"},
}
GROUP_ORDER = [*SPENDING_GROUPS, "Other"]


def spending_group(category: str) -> str:
    return next((g for g, cats in SPENDING_GROUPS.items() if category in cats), "Other")


def _months_back(n: int) -> list[str]:
    now = dt_util.now()
    y, m, out = now.year, now.month, []
    for _ in range(n):
        out.append(f"{y}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out[::-1]


def _top(items, key, limit):
    agg: dict[str, list] = {}
    for x in items:
        a = agg.setdefault(x[key], [0.0, 0])
        a[0] += x["value"]
        a[1] += 1
    rows = sorted(([k, round(v, 2), n] for k, (v, n) in agg.items()), key=lambda r: -r[1])
    return rows[:limit]


def _spending_detail(d: dict) -> dict:
    """History and breakdowns for the spending dashboard. Groups are fixed so charts keep stable colors."""
    spend = d["spending"]
    months24 = _months_back(24)
    months12 = set(months24[-12:])
    this_month = months24[-1]
    monthly = []
    for m in months24:
        g = dict.fromkeys(GROUP_ORDER, 0.0)
        for x in spend:
            if x["month"] == m:
                g[spending_group(x["category"])] += x["value"]
        monthly.append({"month": m, "total": round(sum(g.values()), 2), **{k: round(v, 2) for k, v in g.items()}})
    last12 = [x for x in spend if x["month"] in months12]
    groups12 = dict.fromkeys(GROUP_ORDER, 0.0)
    for x in last12:
        groups12[spending_group(x["category"])] += x["value"]
    years = []
    for y in sorted({x["year"] for x in spend}):
        ys = [x for x in spend if x["year"] == y]
        n_months = len({x["month"] for x in ys}) or 1
        g = dict.fromkeys(GROUP_ORDER, 0.0)
        for x in ys:
            g[spending_group(x["category"])] += x["value"]
        total = sum(x["value"] for x in ys)
        years.append({"year": y, "total": round(total, 2), "months": n_months, "avg_month": round(total / n_months, 2),
                      "transactions": len(ys), **{k: round(v, 2) for k, v in g.items()}})
    total12 = sum(groups12.values())
    return {
        "monthly": monthly,
        "groups_12m": {k: round(v, 2) for k, v in groups12.items()},
        "total_12m": round(total12, 2),
        "avg_month_12m": round(total12 / 12, 2),
        "categories_12m": _top(last12, "category", 25),
        "merchants_12m": _top(last12, "merchant", 15),
        "merchants_month": _top([x for x in spend if x["month"] == this_month], "merchant", 10),
        "by_year": years,
    }


def _flow_attrs(d: dict) -> dict:
    return {"last_12_months": [
        {k: (round(v, 2) if isinstance(v, float) else v) for k, v in m.items()} for m in d["monthly"][-12:]
    ]}


BOND_KEYS = ("name", "symbol", "status", "coupon", "maturity", "frequency", "face", "invested", "coupons_received",
             "coupons_due", "coupons_due_count", "next_coupon", "repayment", "profit_to_maturity", "return_pa",
             "market_value", "market_yield")


def _bonds_profit(d: dict):
    ok = [b for b in d["fixed_income"] if b["profit_to_maturity"] is not None and b["status"] != "distressed"]
    return round(sum(b["profit_to_maturity"] for b in ok), 2) if ok else None


def _bonds_attrs(d: dict) -> dict:
    bonds = [{k: b[k] for k in BOND_KEYS} for b in d["fixed_income"]]
    return {"bonds": bonds, "doubtful": [b["name"] for b in bonds if b["status"] != "ok"]}


def _next_coupon(d: dict):
    dates = [b["next_coupon"] for b in d["fixed_income"] if b["next_coupon"] and b["status"] != "distressed"]
    if not dates:
        return None
    return dt_util.as_utc(datetime.fromisoformat(min(dates)).replace(tzinfo=dt_util.get_default_time_zone()))


def _next_coupon_attrs(d: dict) -> dict:
    ok = [b for b in d["fixed_income"] if b["next_coupon"] and b["status"] != "distressed"]
    if not ok:
        return {}
    first = min(ok, key=lambda b: b["next_coupon"])
    return {"bond": first["name"], "amount": round(first["face"] * first["coupon"] / 100 / (first["frequency"] or 1), 2)}


def _pct(d: dict):
    s = d["summary"]
    return round(s["unrealized"] / s["holdings_cost"] * 100, 2) if s["holdings_cost"] else None


def _last_tx(d: dict):
    last = d["summary"]["last_date"]
    return dt_util.as_utc(datetime.fromisoformat(last).replace(tzinfo=dt_util.get_default_time_zone())) if last else None


SUMMARY: tuple[FISensorDescription, ...] = (
    _money("net_worth", icon="mdi:bank", attrs=_flow_attrs),
    _money("cash", icon="mdi:cash"),
    _money("holdings_value", icon="mdi:chart-pie", attrs=_allocation),
    _money("holdings_cost", icon="mdi:cash-register"),
    _money("unrealized", icon="mdi:trending-up"),
    _money("realized", icon="mdi:cash-check"),
    _money("realized_ytd", icon="mdi:cash-check"),
    _money("total_return", icon="mdi:finance"),
    _money("income", icon="mdi:hand-coin"),
    _money("income_ytd", icon="mdi:hand-coin", attrs=_income_attrs),
    _money("dividends_ytd", icon="mdi:cash-plus"),
    _money("taxes_ytd", icon="mdi:bank-transfer-out"),
    _money("spending_month", icon="mdi:credit-card-outline", attrs=_spending_attrs),
    _money("spending_prev_month", icon="mdi:credit-card-clock-outline"),
    _money("spending_ytd", icon="mdi:credit-card-multiple-outline", attrs=_spending_detail),
    FISensorDescription(key="spending_avg_12m", translation_key="spending_avg_12m", native_unit_of_measurement=EUR,
                        device_class=SensorDeviceClass.MONETARY, state_class=SensorStateClass.TOTAL,
                        suggested_display_precision=2, icon="mdi:chart-bell-curve-cumulative",
                        value_fn=lambda d: _spending_detail(d)["avg_month_12m"]),
    _money("net_contributions", icon="mdi:piggy-bank"),
    FISensorDescription(key="bonds_profit_to_maturity", translation_key="bonds_profit_to_maturity",
                        native_unit_of_measurement=EUR, device_class=SensorDeviceClass.MONETARY,
                        state_class=SensorStateClass.TOTAL, suggested_display_precision=2, icon="mdi:file-certificate-outline",
                        value_fn=_bonds_profit, attrs_fn=_bonds_attrs),
    FISensorDescription(key="next_bond_coupon", translation_key="next_bond_coupon", device_class=SensorDeviceClass.TIMESTAMP,
                        icon="mdi:calendar-cash", value_fn=_next_coupon, attrs_fn=_next_coupon_attrs),
    FISensorDescription(key="unrealized_pct", translation_key="unrealized_pct",
                        native_unit_of_measurement=PERCENTAGE, state_class=SensorStateClass.MEASUREMENT,
                        suggested_display_precision=1, icon="mdi:percent", value_fn=_pct),
    FISensorDescription(key="positions", translation_key="positions", state_class=SensorStateClass.MEASUREMENT,
                        icon="mdi:format-list-numbered", value_fn=lambda d: d["summary"]["positions"]),
    FISensorDescription(key="last_transaction", translation_key="last_transaction",
                        device_class=SensorDeviceClass.TIMESTAMP, icon="mdi:clock-outline", value_fn=_last_tx),
)

def _div(d: dict) -> dict:
    return d.get("dividends") or {}


def _pct(key: str, value_fn, icon: str, attrs=None) -> FISensorDescription:
    return FISensorDescription(key=key, translation_key=key, native_unit_of_measurement=PERCENTAGE,
                               state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=2, icon=icon,
                               value_fn=value_fn, attrs_fn=attrs)


def _eur(key: str, value_fn, icon: str, attrs=None) -> FISensorDescription:
    return FISensorDescription(key=key, translation_key=key, native_unit_of_measurement=EUR,
                               device_class=SensorDeviceClass.MONETARY, state_class=SensorStateClass.TOTAL,
                               suggested_display_precision=2, icon=icon, value_fn=value_fn, attrs_fn=attrs)


def _date_ts(value: str | None):
    if not value:
        return None
    return dt_util.as_utc(datetime.fromisoformat(value).replace(tzinfo=dt_util.get_default_time_zone()))


def _bench(key: str):
    return lambda d: (_div(d).get("benchmarks") or {}).get(key)


def _dividend_income_attrs(d: dict) -> dict:
    x = _div(d)
    return {k: x.get(k) for k in ("monthly_income", "annual_income_net", "calendar", "upcoming", "per_year",
                                  "portfolio_yield_pct", "tax_rate_pct")}


def _yield_attrs(d: dict) -> dict:
    x = _div(d)
    return {"yield_on_cost_pct": x.get("yield_on_cost_pct"), "portfolio_yield_pct": x.get("portfolio_yield_pct"),
            "stocks": x.get("stocks"), "watchlist": x.get("watchlist"), "ranking": x.get("ranking"),
            "benchmarks": {k: v for k, v in (x.get("benchmarks") or {}).items() if not k.endswith("history")}}


def _received_attrs(d: dict) -> dict:
    x = _div(d)
    return {k: x.get(k) for k in ("received_prev_12m", "growth_12m_pct", "received_ytd", "received_total",
                                  "received_total_net")}


def _next(d: dict) -> dict:
    return _div(d).get("next") or {}


DIVIDENDS: tuple[FISensorDescription, ...] = (
    _eur("dividend_income_forward", lambda d: _div(d).get("annual_income"), "mdi:cash-clock", _dividend_income_attrs),
    _pct("dividend_yield", lambda d: _div(d).get("yield_pct"), "mdi:percent-circle-outline", _yield_attrs),
    _pct("dividend_yield_on_cost", lambda d: _div(d).get("yield_on_cost_pct"), "mdi:percent-box-outline"),
    _eur("dividends_12m", lambda d: _div(d).get("received_12m"), "mdi:cash-check", _received_attrs),
    FISensorDescription(key="next_dividend", translation_key="next_dividend", device_class=SensorDeviceClass.TIMESTAMP,
                        icon="mdi:calendar-star", attrs_fn=_next,
                        value_fn=lambda d: _date_ts(_next(d).get("next_pay_date") or _next(d).get("next_ex_date"))),
    _pct("ecb_deposit_rate", _bench("ecb_deposit_rate"), "mdi:bank-outline",
         lambda d: {"period": _bench("ecb_period")(d), "history": _bench("ecb_history")(d)}),
    _pct("inflation_rate", _bench("inflation"), "mdi:chart-line-variant",
         lambda d: {"period": _bench("inflation_period")(d), "history": _bench("inflation_history")(d)}),
    _pct("tr_cash_interest_rate", _bench("tr_cash_rate"), "mdi:piggy-bank", lambda d: {"date": _bench("tr_cash_date")(d)}),
    _pct("real_dividend_yield", _bench("real_yield"), "mdi:scale-balance"),
)

def _tax(d: dict) -> dict:
    return d.get("tax") or {}


def _tax_attrs(d: dict) -> dict:
    return {k: v for k, v in _tax(d).items()}


TAXES: tuple[FISensorDescription, ...] = (
    _eur("tax_allowance_left", lambda d: _tax(d).get("allowance_left"), "mdi:shield-check-outline", _tax_attrs),
    _eur("tax_expected", lambda d: _tax(d).get("tax_expected"), "mdi:bank-transfer-out",
         lambda d: {k: _tax(d).get(k) for k in ("withheld_ytd", "taxable_ytd", "taxable_expected", "expected_rest")}),
    _eur("tax_refund_estimate", lambda d: (_tax(d).get("personal") or {}).get("saving"), "mdi:cash-refund",
         lambda d: _tax(d).get("personal") or {}),
)

ASSET_ICONS = {"STOCK": "mdi:chart-line", "FUND": "mdi:chart-areaspline", "BOND": "mdi:file-certificate-outline",
               "CRYPTO": "mdi:bitcoin"}
