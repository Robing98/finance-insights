"""Energy and water costs from meter readings and contracts.

Pure Python without Home Assistant imports. Money in EUR, gross.
"""
from __future__ import annotations

from datetime import date, timedelta

UTILITY_TYPES = ["electricity", "gas", "water", "heat"]
BILLING_UNIT = {"electricity": "kWh", "gas": "kWh", "water": "m³", "heat": "kWh"}


def to_billing_unit(amount: float, unit: str | None, utility: str, kwh_per_m3: float | None) -> float | None:
    """Meter unit to the unit the price refers to. None if it can't be converted."""
    u = (unit or "").replace("m3", "m³").strip()
    target = BILLING_UNIT[utility]
    if u == target:
        return amount
    factors = {("Wh", "kWh"): 1 / 1000, ("MWh", "kWh"): 1000, ("L", "m³"): 1 / 1000, ("l", "m³"): 1 / 1000}
    if (u, target) in factors:
        return amount * factors[(u, target)]
    if utility == "gas" and u == "m³" and kwh_per_m3:
        return amount * kwh_per_m3
    return None


def _d(value) -> date | None:
    if value in (None, ""):
        return None
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def _add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 29 February
        return d.replace(year=d.year + years, day=28)


def _months_between(start: date, end: date) -> int:
    """Monthly payments due from start up to and including end (paid on the start day each month)."""
    if end < start:
        return 0
    months = (end.year - start.year) * 12 + end.month - start.month
    return months + (1 if end.day >= start.day else 0)


def contract_for(contracts: list[dict], day: date) -> dict | None:
    valid = [c for c in contracts if _d(c["start"]) <= day and (not c.get("end") or day <= _d(c["end"]))]
    return max(valid, key=lambda c: _d(c["start"])) if valid else None


def day_cost(contracts: list[dict], day: date, amount: float) -> float | None:
    c = contract_for(contracts, day)
    if c is None:
        return None
    return amount * float(c.get("unit_price") or 0) + float(c.get("base_price") or 0) * 12 / 365


def _r(v, n=2):
    return round(v, n) if v is not None else None


def analyze_utility(daily: dict[date, float], contracts: list[dict], today: date, *,
                    devices: dict[str, float] | None = None) -> dict:
    """daily: consumption per day in the billing unit. devices: name -> consumption this month (billing unit)."""
    contracts = sorted(contracts, key=lambda c: _d(c["start"]))
    month_start = today.replace(day=1)
    year_start = today.replace(month=1, day=1)

    def total(start: date, end: date):
        qty = cost = 0.0
        priced = False
        day = start
        while day <= end:
            amount = daily.get(day, 0.0)
            qty += amount
            c = day_cost(contracts, day, amount)
            if c is not None:
                cost += c
                priced = True
            day += timedelta(days=1)
        return qty, (cost if priced else None)

    q_today, c_today = total(today, today)
    q_month, c_month = total(month_start, today)
    q_year, c_year = total(year_start, today)

    monthly = []
    for i in range(12, -1, -1):
        y, m = divmod(today.year * 12 + today.month - 1 - i, 12)
        start = date(y, m + 1, 1)
        end = (date(y + (m == 11), (m + 1) % 12 + 1, 1) - timedelta(days=1))
        q, c = total(start, min(end, today))
        monthly.append({"month": start.strftime("%Y-%m"), "consumption": _r(q, 3), "cost": _r(c)})

    active = contract_for(contracts, today)
    period = forecast = None
    if active:
        start = _d(active["start"])
        period_start = start
        while _add_years(period_start, 1) <= today:
            period_start = _add_years(period_start, 1)
        period_end = _add_years(period_start, 1) - timedelta(days=1)
        if active.get("end"):
            period_end = min(period_end, _d(active["end"]))
        q_so_far, c_so_far = total(period_start, today)

        # Rest of the period: same days last year where available, otherwise the recent daily average.
        recent = [daily[d] for d in (today - timedelta(days=i) for i in range(1, 31)) if d in daily]
        avg = sum(recent) / len(recent) if recent else (sum(daily.values()) / len(daily) if daily else 0.0)
        method = "recent average"
        rest_qty = rest_cost = 0.0
        last_year_days = 0
        day = today + timedelta(days=1)
        while day <= period_end:
            ly = _add_years(day, -1)
            near = [daily[x] for x in (ly + timedelta(days=k) for k in range(-3, 4)) if x in daily]
            if near:
                amount = sum(near) / len(near)
                last_year_days += 1
            else:
                amount = avg
            rest_qty += amount
            rest_cost += day_cost(contracts, day, amount) or 0.0
            day += timedelta(days=1)
        remaining_days = (period_end - today).days
        if remaining_days and last_year_days >= remaining_days * 0.8:
            method = "last year"
        expected = (c_so_far or 0.0) + rest_cost
        advance = float(active.get("advance") or 0)
        months = _months_between(period_start, period_end)
        paid = advance * _months_between(period_start, today)
        advances_total = advance * months
        bonus = float(active.get("bonus") or 0)
        settlement = advances_total - expected + bonus
        end = _d(active.get("end"))
        notice = end - timedelta(weeks=int(active["notice_weeks"])) if end and active.get("notice_weeks") else None
        ly_start, ly_end = _add_years(period_start, -1), _add_years(today, -1)
        ly_qty = sum(v for d, v in daily.items() if ly_start <= d <= ly_end)
        ly_complete = sum(1 for i in range((ly_end - ly_start).days + 1) if ly_start + timedelta(days=i) in daily)
        period = dict(
            supplier=active.get("supplier"), start=period_start.isoformat(), end=period_end.isoformat(),
            consumption=_r(q_so_far, 3), cost=_r(c_so_far), advances_paid=_r(paid), advances_total=_r(advances_total),
            unit_price=active.get("unit_price"), base_price=active.get("base_price"), advance=advance, bonus=bonus or None,
            contract_end=end.isoformat() if end else None, notice_deadline=notice.isoformat() if notice else None,
            days_to_notice=(notice - today).days if notice else None,
            last_year_consumption=_r(ly_qty, 3) if ly_complete >= (ly_end - ly_start).days * 0.8 and ly_qty else None,
        )
        forecast = dict(
            method=method, expected_consumption=_r(q_so_far + rest_qty, 3), expected_cost=_r(expected),
            settlement=_r(settlement), suggested_advance=_r((expected - bonus) / months) if months else None,
        )

    device_costs = []
    unit_price = float(active.get("unit_price") or 0) if active else None
    for name, qty in sorted((devices or {}).items(), key=lambda kv: -kv[1]):
        device_costs.append({"name": name, "consumption": _r(qty, 3),
                             "cost": _r(qty * unit_price) if unit_price is not None else None})

    days_with_data = len([d for d in daily if d <= today])
    return dict(
        consumption_today=_r(q_today, 3), cost_today=_r(c_today), consumption_month=_r(q_month, 3), cost_month=_r(c_month),
        consumption_year=_r(q_year, 3), cost_year=_r(c_year), monthly=monthly, period=period, forecast=forecast,
        devices=device_costs, contracts=[{k: c.get(k) for k in ("supplier", "start", "end", "unit_price", "base_price", "advance",
                                                               "bonus", "notice_weeks")} for c in contracts],
        days_with_data=days_with_data, has_contract=bool(contracts),
    )
