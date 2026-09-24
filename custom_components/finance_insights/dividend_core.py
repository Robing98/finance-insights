"""Dividend analysis: yields, payback, growth, calendar, and benchmarks.

Pure Python without Home Assistant imports. Amounts in EUR are gross (before tax)
unless a key ends in _net.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import median

from .market_data import DividendEvent

EURO_COUNTRIES = {"AT", "BE", "CY", "DE", "EE", "ES", "FI", "FR", "GR", "HR", "IE", "IT", "LT", "LU", "LV", "MT", "NL",
                  "PT", "SI", "SK"}


def _d(value) -> date | None:
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _r(value, digits=2):
    return round(value, digits) if value is not None else None


def _add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    y += d.year
    m += 1
    last = [31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return date(y, m, min(d.day, last))


class _Fx:
    def __init__(self, rates: dict[str, float]) -> None:
        self.rates = rates

    def to_eur(self, amount: float | None, currency: str | None, isin: str) -> float | None:
        if amount is None:
            return None
        cur = currency or ("EUR" if isin[:2] in EURO_COUNTRIES else None)
        if cur == "EUR":
            return amount
        rate = self.rates.get(cur or "")
        return amount / rate if rate else None


def _gaps(dates: list[date]) -> float | None:
    gaps = [(b - a).days for a, b in zip(dates, dates[1:], strict=False) if (b - a).days > 20]
    return median(gaps) if gaps else None


def stock_view(isin: str, name: str, events: list[DividendEvent], own: list[dict], fx: _Fx, today: date, *,
               shares: float = 0.0, cost: float = 0.0, value: float | None = None, price: float | None = None,
               unrealized: float | None = None) -> dict:
    """own: this stock's dividend rows from the broker (date, amount gross, tax negative)."""
    events = sorted(events, key=lambda e: e.ex_date)
    past = [e for e in events if e.ex_date <= today]
    future = [e for e in events if e.ex_date > today or (e.pay_date and e.pay_date >= today)]
    year_ago = today - timedelta(days=365)
    ttm = [e for e in past if e.ex_date > year_ago]
    currency = next((e.currency for e in reversed(events) if e.currency), None)
    source = events[-1].source if events else ("payments" if own else None)

    # Payments per year: last 12 months, or the average of the last 3 years for irregular payers.
    freq = len(ttm) or round(len([e for e in past if e.ex_date > today - timedelta(days=3 * 365)]) / 3)
    price_eur = price if price is not None else (value / shares if value and shares else None)

    own_gross = sum(r["amount"] or 0 for r in own)
    own_tax = -sum(r["tax"] or 0 for r in own)
    own_12m = sum(r["amount"] or 0 for r in own if _d(r["date"]) > year_ago)
    tax_rate = own_tax / own_gross if own_gross > 0 else None

    ttm_local = sum(e.amount for e in ttm)
    dps_eur = fx.to_eur(ttm_local, currency, isin) if ttm else None
    if dps_eur is None and ttm and own_12m and shares:
        dps_eur = own_12m / shares  # currency unknown: fall back to what actually arrived
    if not events and own_12m and shares:
        dps_eur = own_12m / shares
        freq = len([r for r in own if _d(r["date"]) > year_ago])

    # Yearly dividend per share for complete years, for growth and cuts.
    by_year: dict[int, float] = defaultdict(float)
    for e in past:
        by_year[e.ex_date.year] += e.amount
    # A year the position was bought into holds part of a cycle. Growing from one payment to four
    # is not dividend growth, so a first year with fewer payments than the others is dropped.
    per_year: dict[int, int] = defaultdict(int)
    for e in past:
        per_year[e.ex_date.year] += 1
    years = [y for y in sorted(by_year) if y < today.year]
    full = max((per_year[y] for y in years), default=0)
    while len(years) > 1 and per_year[years[0]] < full:
        years = years[1:]
    cagr = None
    span = years[-6:] if len(years) >= 3 else []
    if span and by_year[span[0]] > 0:
        n = span[-1] - span[0]
        cagr = ((by_year[span[-1]] / by_year[span[0]]) ** (1 / n) - 1) * 100 if n > 0 else None
    no_cut = 0
    for a, b in zip(reversed(years[:-1]), reversed(years[1:]), strict=False):
        if by_year[b] >= by_year[a] * 0.99:
            no_cut += 1
        else:
            break

    # Next ex date and payment: announced if known, otherwise estimated from the rhythm.
    ex_dates = [e.ex_date for e in past]
    gap = _gaps(ex_dates[-12:])
    pay_lags = [(e.pay_date - e.ex_date).days for e in past[-8:] if e.pay_date]
    if not pay_lags and own and past:
        # No pay dates from the provider: learn the delay from your own payments.
        for r in own:
            paid = _d(r["date"])
            before = [e.ex_date for e in past if 0 <= (paid - e.ex_date).days <= 60]
            if before:
                pay_lags.append((paid - max(before)).days)
    next_ex = next_pay = next_amount = None
    estimated = False
    if future:
        nxt = future[0]
        next_ex, next_pay, next_amount = nxt.ex_date, nxt.pay_date, fx.to_eur(nxt.amount, nxt.currency or currency, isin)
        if next_pay is None and pay_lags:
            next_pay = next_ex + timedelta(days=round(median(pay_lags)))
    elif past and gap:
        estimated = True
        next_ex = past[-1].ex_date
        while next_ex <= today:
            next_ex += timedelta(days=round(gap))
        next_pay = next_ex + timedelta(days=round(median(pay_lags))) if pay_lags else None
        next_amount = fx.to_eur(past[-1].amount, past[-1].currency or currency, isin)
    elif not events and len(own) >= 2:
        estimated = True
        pay_dates = sorted(_d(r["date"]) for r in own)
        own_gap = _gaps(pay_dates)
        if own_gap:
            next_pay = pay_dates[-1]
            while next_pay <= today:
                next_pay += timedelta(days=round(own_gap))
            last = max(own, key=lambda r: r["date"])
            next_amount = (last["amount"] or 0) / shares if shares else None

    annual = dps_eur * shares if dps_eur is not None and shares else None
    yield_pct = dps_eur / price_eur * 100 if dps_eur is not None and price_eur else None
    avg_cost = cost / shares if shares and cost else None
    yoc = dps_eur / avg_cost * 100 if dps_eur is not None and avg_cost else None
    remaining = cost - own_gross if cost else None
    return dict(
        isin=isin, name=name, held=shares > 0, source=source, currency=currency, shares=_r(shares, 6),
        price=_r(price_eur, 4), value=_r(value), cost=_r(cost), frequency=freq or None,
        dps_ttm=_r(ttm_local, 4) if ttm else None, dps_eur=_r(dps_eur, 4), yield_pct=_r(yield_pct),
        yield_on_cost_pct=_r(yoc), annual_income=_r(annual), annual_income_net=_r(annual * (1 - tax_rate))
        if annual is not None and tax_rate is not None else None,
        received=_r(own_gross), received_net=_r(own_gross - own_tax), received_12m=_r(own_12m), tax_rate_pct=_r(tax_rate * 100 if tax_rate is not None else None, 1),
        payback_pct=_r(own_gross / cost * 100 if cost else None),
        years_to_payback=_r(remaining / annual, 1) if annual and remaining and remaining > 0 else None,
        dividend_share_of_return_pct=_r(own_gross / (own_gross + unrealized) * 100)
        if unrealized is not None and own_gross + unrealized > 0 else None,
        growth_pct=_r(cagr, 1), growth_years=(span[-1] - span[0]) if cagr is not None else None, years_without_cut=no_cut if len(years) >= 2 else None,
        last_ex_date=past[-1].ex_date.isoformat() if past else None,
        next_ex_date=next_ex.isoformat() if next_ex else None, next_pay_date=next_pay.isoformat() if next_pay else None,
        next_amount=_r(next_amount, 4), next_total=_r(next_amount * shares) if next_amount is not None and shares else None,
        estimated=estimated, gap_days=round(gap) if gap else None,
        years={str(y): _r(by_year[y], 4) for y in years[-10:]},
    )


def _projected_payments(s: dict, today: date, horizon: date) -> list[tuple[date, float]]:
    """Expected payments per stock until horizon, spaced like the past ones."""
    if not s["shares"] or s["next_amount"] is None:
        return []
    first = _d(s["next_pay_date"]) or _d(s["next_ex_date"])
    if first is None:
        return []
    out, day = [], first
    step = s["gap_days"] or (365 // (s["frequency"] or 1))
    while day <= horizon and step > 20:
        if day >= today:
            out.append((day, s["next_amount"] * s["shares"]))
        day += timedelta(days=step)
    return out


def tr_cash_rate(rows: list[dict], today: date) -> dict | None:
    """Effective yearly rate of the latest cash interest payment, from the average balance before it."""
    rows = sorted(rows, key=lambda r: r["datetime"])
    pays = [r for r in rows if r["type"] == "INTEREST_PAYMENT" and not r["symbol"] and (r["amount"] or 0) > 0]
    if len(pays) < 2:
        return None
    last, prev = pays[-1], pays[-2]
    start, end = _d(prev["date"]), _d(last["date"])
    days = (end - start).days
    if days < 20:
        return None
    balance, daily = 0.0, {}
    for r in rows:
        if _d(r["date"]) >= end:
            break
        balance += r["cash"] or 0
        daily[_d(r["date"])] = balance
    bal, total = 0.0, 0.0
    before = [d for d in daily if d <= start]
    bal = daily[max(before)] if before else 0.0
    for i in range(days):
        day = start + timedelta(days=i)
        bal = daily.get(day, bal)
        total += bal
    avg = total / days
    if avg <= 1:
        return None
    return {"rate_pct": round(last["amount"] / avg * 365 / days * 100, 2), "date": end.isoformat(), "balance": round(avg, 2)}


def _latest(series: list[tuple[str, float]] | None):
    return series[-1] if series else (None, None)


def analyze_dividends(result: dict, rows: list[dict], events: dict[str, list[DividendEvent]], fx_rates: dict[str, float],
                      benchmarks: dict[str, list[tuple[str, float]]], today: date, watchlist: list[dict] | None = None) -> dict:
    """result: tr_core.analyze() output. events: per ISIN. watchlist: [{isin, name, price}] with EUR prices."""
    fx = _Fx(fx_rates)
    div_rows = [r for r in rows if r["type"] == "DIVIDEND"]
    by_isin = defaultdict(list)
    for r in div_rows:
        by_isin[r["symbol"]].append(r)

    stocks = []
    for h in result["holdings"]:
        if h["asset_class"] not in ("STOCK", "FUND") or (not events.get(h["symbol"]) and not by_isin.get(h["symbol"])):
            continue
        stocks.append(stock_view(h["symbol"], h["name"], events.get(h["symbol"], []), by_isin.get(h["symbol"], []), fx, today,
                                 shares=h["shares"], cost=h["cost"], value=h["value"], unrealized=h["unrealized"]))
    held = {s["isin"] for s in stocks}
    watch = []
    for w in watchlist or []:
        if w["isin"] in held or not events.get(w["isin"]):
            continue
        watch.append(stock_view(w["isin"], w.get("name") or w["isin"], events[w["isin"]], [], fx, today, price=w.get("price")))

    ecb_period, ecb = _latest(benchmarks.get("ecb_deposit_rate"))
    hicp_period, hicp = _latest(benchmarks.get("inflation"))
    cash = tr_cash_rate(rows, today)
    bonds = [b for b in result.get("fixed_income") or [] if b.get("return_pa") is not None and b.get("status") == "ok"]
    bond_ytm = sum(b["return_pa"] * b["invested"] for b in bonds) / sum(b["invested"] for b in bonds) if bonds and sum(b["invested"] for b in bonds) else None

    for s in stocks + watch:
        y = s["yield_pct"]
        s["vs_ecb_pct"] = _r(y - ecb) if y is not None and ecb is not None else None
        s["real_yield_pct"] = _r(y - hicp) if y is not None and hicp is not None else None

    income = sum(s["annual_income"] or 0 for s in stocks)
    div_value = sum(s["value"] or 0 for s in stocks if s["annual_income"])
    div_cost = sum(s["cost"] or 0 for s in stocks if s["annual_income"])
    all_value = sum(h["value"] or 0 for h in result["holdings"])
    year_ago = today - timedelta(days=365)
    received_12m = sum(r["amount"] or 0 for r in div_rows if _d(r["date"]) > year_ago)
    received_prev = sum(r["amount"] or 0 for r in div_rows if year_ago - timedelta(days=365) < _d(r["date"]) <= year_ago)
    # The window before this one is only comparable once it is a whole year of receiving, not the
    # weeks after the first purchase.
    first_dividend = min((_d(r["date"]) for r in div_rows), default=None)
    full_prev_window = bool(first_dividend and first_dividend <= year_ago - timedelta(days=365))
    received_ytd = sum(r["amount"] or 0 for r in div_rows if _d(r["date"]).year == today.year)
    tax = -sum(r["tax"] or 0 for r in div_rows)
    gross = sum(r["amount"] or 0 for r in div_rows)
    portfolio_yield = income / div_value * 100 if div_value else None

    horizon = _add_months(today, 12)
    months = [_add_months(date(today.year, today.month, 1), i).strftime("%Y-%m") for i in range(12)]
    calendar = {m: {"month": m, "amount": 0.0, "stocks": []} for m in months}
    upcoming = []
    for s in stocks:
        for day, amount in _projected_payments(s, today, horizon):
            m = day.strftime("%Y-%m")
            if m in calendar:
                calendar[m]["amount"] += amount
                if s["name"] not in calendar[m]["stocks"]:
                    calendar[m]["stocks"].append(s["name"])
        if s["next_ex_date"] or s["next_pay_date"]:
            upcoming.append({k: s[k] for k in ("name", "isin", "next_ex_date", "next_pay_date", "next_amount", "next_total", "estimated")})
    upcoming.sort(key=lambda u: u["next_ex_date"] or u["next_pay_date"])
    per_year = defaultdict(float)
    for r in div_rows:
        per_year[_d(r["date"]).year] += r["amount"] or 0

    def history(key):
        """Last value per month, for charts."""
        monthly: dict[str, float] = {}
        for p, v in benchmarks.get(key) or []:
            monthly[p[:7]] = v
        return [{"period": p, "value": v} for p, v in sorted(monthly.items())][-36:]

    return dict(
        stocks=sorted(stocks, key=lambda s: -(s["annual_income"] or 0)),
        watchlist=sorted(watch, key=lambda s: -(s["yield_pct"] or 0)),
        ranking=[{k: s[k] for k in ("name", "isin", "held", "yield_pct", "yield_on_cost_pct", "growth_pct", "years_without_cut",
                                     "frequency", "next_ex_date", "vs_ecb_pct", "real_yield_pct")}
                 for s in sorted(stocks + watch, key=lambda s: -(s["yield_pct"] or 0))],
        annual_income=round(income, 2), annual_income_net=round(income * (1 - tax / gross), 2) if gross > 0 else None,
        monthly_income=round(income / 12, 2),
        yield_pct=_r(portfolio_yield), yield_on_cost_pct=_r(income / div_cost * 100 if div_cost else None),
        portfolio_yield_pct=_r(income / all_value * 100 if all_value else None),
        received_total=round(gross, 2), received_total_net=round(gross - tax, 2), received_12m=round(received_12m, 2),
        received_prev_12m=round(received_prev, 2), received_ytd=round(received_ytd, 2),
        growth_12m_pct=_r((received_12m / received_prev - 1) * 100 if received_prev and full_prev_window else None, 1),
        tax_rate_pct=_r(tax / gross * 100 if gross else None, 1),
        calendar=[{**c, "amount": round(c["amount"], 2)} for c in calendar.values()],
        upcoming=upcoming[:15], per_year={str(y): round(v, 2) for y, v in sorted(per_year.items())},
        next=upcoming[0] if upcoming else None,
        benchmarks=dict(
            ecb_deposit_rate=ecb, ecb_period=ecb_period, inflation=hicp, inflation_period=hicp_period,
            tr_cash_rate=cash["rate_pct"] if cash else None, tr_cash_date=cash["date"] if cash else None,
            bonds_ytm=_r(bond_ytm), real_yield=_r(portfolio_yield - hicp) if portfolio_yield is not None and hicp is not None else None,
            vs_ecb=_r(portfolio_yield - ecb) if portfolio_yield is not None and ecb is not None else None,
            ecb_history=history("ecb_deposit_rate"), inflation_history=history("inflation"),
        ),
        updated=datetime.now().isoformat(timespec="seconds"),
    )
