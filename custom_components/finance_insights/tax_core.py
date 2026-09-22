"""Capital income tax estimates for people taxed in Germany.

Pure Python without Home Assistant imports. Everything here is an estimate from the
exports: Trade Republic's tax report and the tax assessment are binding.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta

from .tr_core import Ledger, z

# § 32a EStG. Later years reuse the newest known tariff and say so in the output.
TARIFFS = {
    2025: dict(basic=12096, zone2=17443, zone3=68480, zone4=277825, a2=932.30, a3=176.64, c3=1015.13, c4=10911.92, c5=19246.67),
    2026: dict(basic=12348, zone2=17799, zone3=69878, zone4=277825, a2=914.51, a3=173.10, c3=1034.87, c4=11135.63, c5=19470.38),
}
SAVER_ALLOWANCE = 1000.0            # Sparer-Pauschbetrag per person, doubled for joint assessment
FUND_TAXABLE = 0.7                  # Teilfreistellung for equity funds; bond funds are not told apart
PRIVATE_SALES_LIMIT = 1000.0        # Freigrenze for private sales (crypto) since 2024: above it, all is taxable
OTHER_INCOME_LIMIT = 256.0          # Freigrenze for other income such as staking rewards
MIN_LOSS = 10.0                     # smaller losses are not worth listing
MIN_BENEFIT = 5.0                   # below this a sell and rebuy does not pay for fees and spread
EXCLUDED_KINDS = ("Saveback", "Stock perks", "Crypto rewards", "Bonuses and gifts")


def tariff_year(year: int) -> int:
    known = [y for y in TARIFFS if y <= year]
    return max(known) if known else min(TARIFFS)


def income_tax(zve: float, year: int, joint: bool = False) -> float:
    """Income tax on the taxable income (zu versteuerndes Einkommen), without Soli and church tax."""
    if joint:
        return 2 * income_tax(zve / 2, year)
    t = TARIFFS[tariff_year(year)]
    x = math.floor(max(zve, 0.0))
    if x <= t["basic"]:
        return 0.0
    if x <= t["zone2"]:
        y = (x - t["basic"]) / 10000
        tax = (t["a2"] * y + 1400) * y
    elif x <= t["zone3"]:
        y = (x - t["zone2"]) / 10000
        tax = (t["a3"] * y + 2397) * y + t["c3"]
    elif x <= t["zone4"]:
        tax = 0.42 * x - t["c4"]
    else:
        tax = 0.45 * x - t["c5"]
    return float(math.floor(tax))


def flat_rate(church: float) -> float:
    """Abgeltungsteuer with Soli and church tax per euro of taxable capital income (§ 32d EStG)."""
    return (1.055 + church) / (4 + church)


def _add_year(d: date) -> date:
    try:
        return d.replace(year=d.year + 1)
    except ValueError:
        return d.replace(year=d.year + 1, day=28)


def _d(value) -> date | None:
    return date.fromisoformat(str(value)[:10]) if value else None


def _pot_year(stock: float, general: float, carry_stock: float, carry_general: float):
    """Net one year the way German banks do: stock losses only against stock gains,
    other losses against everything. Returns (taxable, carry_stock, carry_general)."""
    stock_net = stock - carry_stock
    general_net = general - carry_general
    if general_net < 0 < stock_net:
        offset = min(-general_net, stock_net)
        stock_net -= offset
        general_net += offset
    # + 0.0 turns -0.0 into 0.0 for display
    return max(stock_net, 0.0) + max(general_net, 0.0), max(-stock_net, 0.0) + 0.0, max(-general_net, 0.0) + 0.0


def _classes(rows: list[dict], ledger: Ledger) -> dict[str, str]:
    out = {sym: q["asset_class"] for sym, q in ledger.pos.items() if q["asset_class"]}
    for r in rows:
        if r["symbol"] and r.get("asset_class") and r["symbol"] not in out:
            out[r["symbol"]] = r["asset_class"]
    return out


def _yearly(rows: list[dict], ledger: Ledger, classes: dict[str, str]) -> dict[int, dict]:
    years: dict[int, dict] = defaultdict(lambda: dict(stock=0.0, general=0.0, income=0.0, realized=0.0,
                                                      withheld=0.0, private_sales=0.0, excluded=defaultdict(float)))
    for r in rows:
        y = years[r["year"]]
        y["withheld"] -= z(r["tax"]) + (z(r["amount"]) if r["bucket"] == "tax" else 0.0)
        if r["bucket"] != "income":
            continue
        if r["income_kind"] in EXCLUDED_KINDS:
            y["excluded"][r["income_kind"]] += r["income_value"]
            continue
        factor = FUND_TAXABLE if classes.get(r["symbol"]) == "FUND" else 1.0
        y["general"] += r["income_value"] * factor
        y["income"] += r["income_value"] * factor
    for x in ledger.realized:
        y = years[x["year"]]
        cls = x["asset_class"]
        if cls == "CRYPTO":
            sold = _d(x["date"])
            per_share = x["proceeds"] / x["shares"] if x["shares"] else 0.0
            for n, cost, day in x.get("lots") or []:
                acquired = _d(day)
                if acquired is None or sold <= _add_year(acquired):
                    y["private_sales"] += n * (per_share - cost)
            continue
        gain = x["gain"] * (FUND_TAXABLE if cls == "FUND" else 1.0)
        y["realized"] += gain
        if cls == "STOCK":
            y["stock"] += gain
        else:
            y["general"] += gain
    return years


def _reset_candidates(holdings, ledger, room_stock, room_general):
    out = []
    for h in holdings:
        if h["asset_class"] not in ("STOCK", "FUND") or not h["price"] or (h["unrealized"] or 0) <= 0:
            continue
        q = ledger.pos.get(h["symbol"])
        if not q or not q["lots"]:
            continue
        factor = FUND_TAXABLE if h["asset_class"] == "FUND" else 1.0
        target = room_stock if h["asset_class"] == "STOCK" else room_general
        price, shares, taxable, covers = h["price"], 0.0, 0.0, False
        for n, cost, _day in q["lots"]:                   # FIFO: older lots, including losing ones, go first
            per = (price - cost) * factor
            if per > 0 and taxable + n * per >= target:
                shares += (target - taxable) / per
                taxable, covers = target, True
                break
            shares += n
            taxable += n * per
        shares = math.floor(shares * 1000) / 1000
        # Selling a whole position for a small part of the allowance is not worth the spread.
        if shares <= 0 or taxable < min(target * 0.25, 50.0):
            continue
        out.append(dict(name=h["name"], symbol=h["symbol"], asset_class=h["asset_class"], shares=shares,
                        proceeds=round(shares * price, 2), taxable_gain=round(taxable, 2),
                        gain=round(taxable / factor, 2), covers=covers))
    out.sort(key=lambda c: (not c["covers"], c["proceeds"]))
    return out[:5]


def _loss_candidates(holdings, taxable_stock: float, taxable_all: float, rate: float):
    out = []
    for h in holdings:
        if h["asset_class"] not in ("STOCK", "FUND", "BOND") or (h["unrealized"] or 0) > -MIN_LOSS:
            continue
        loss = -h["unrealized"] * (FUND_TAXABLE if h["asset_class"] == "FUND" else 1.0)
        usable = min(loss, taxable_stock if h["asset_class"] == "STOCK" else taxable_all)
        out.append(dict(name=h["name"], symbol=h["symbol"], asset_class=h["asset_class"],
                        pot="stock" if h["asset_class"] == "STOCK" else "general", loss=round(loss, 2),
                        saves_now=round(max(usable, 0.0) * rate, 2)))
    out.sort(key=lambda c: -c["saves_now"])
    return out[:5]


def _crypto(holdings, ledger, today: date):
    out = []
    for h in holdings:
        if h["asset_class"] != "CRYPTO":
            continue
        q = ledger.pos.get(h["symbol"])
        if not q:
            continue
        free = young = young_gain = 0.0
        next_free = None
        for n, cost, day in q["lots"]:
            acquired = _d(day)
            if acquired and today > _add_year(acquired):
                free += n
            else:
                young += n
                if h["price"]:
                    young_gain += n * (h["price"] - cost)
                if acquired and (next_free is None or _add_year(acquired) < next_free):
                    next_free = _add_year(acquired)
        out.append(dict(name=h["name"], symbol=h["symbol"], tax_free_shares=round(free, 8), taxable_shares=round(young, 8),
                        taxable_gain=round(young_gain, 2),
                        next_tax_free=(next_free + timedelta(days=1)).isoformat() if next_free else None))
    return out


def analyze_tax(rows: list[dict], holdings: list[dict], today: date, *, allowance: float | None = None,
                other_income: float | None = None, joint: bool = False, church: float = 0.0,
                expected_dividends: float = 0.0) -> dict:
    """allowance: Freistellungsauftrag at Trade Republic. other_income: expected taxable income
    without capital income, for the Günstigerprüfung and the NV-Bescheinigung. expected_dividends:
    dividends still expected this year (gross)."""
    full_allowance = SAVER_ALLOWANCE * (2 if joint else 1)
    fsa = full_allowance if allowance is None else float(allowance)
    ledger = Ledger().run(rows)
    classes = _classes(rows, ledger)
    years = _yearly(rows, ledger, classes)
    rate = flat_rate(church)

    carry_stock = carry_general = 0.0
    history = []
    for y in sorted(k for k in years if k < today.year):
        v = years[y]
        taxable, carry_stock, carry_general = _pot_year(v["stock"], v["general"], carry_stock, carry_general)
        history.append(dict(year=y, taxable=round(taxable, 2), withheld=round(v["withheld"], 2),
                            loss_pot_stock=round(carry_stock, 2), loss_pot_general=round(carry_general, 2)))

    cur = years[today.year]
    # Cash interest arrives monthly for the previous month; the December share is paid in January.
    interest = [r for r in rows if r["bucket"] == "income" and r["income_kind"] == "Cash interest"
                and (today.year * 12 + today.month) - (r["year"] * 12 + int(r["month"][5:])) in (1, 2, 3)]
    interest_rest = sum(r["income_value"] for r in interest) / 3 * (12 - today.month)
    rest = max(expected_dividends, 0.0) + interest_rest

    taxable_ytd, _, _ = _pot_year(cur["stock"], cur["general"], carry_stock, carry_general)
    taxable, pot_stock, pot_general = _pot_year(cur["stock"], cur["general"] + rest, carry_stock, carry_general)
    stock_taxable = max(cur["stock"] - carry_stock, 0.0)
    used = min(fsa, taxable)
    left = max(fsa - taxable, 0.0)
    benefit = left * rate

    reset = _reset_candidates(holdings, ledger, left + pot_stock + pot_general, left + pot_general) \
        if benefit >= MIN_BENEFIT else []
    above = max(taxable - fsa, 0.0)
    losses = _loss_candidates(holdings, min(stock_taxable, above), above, rate)
    crypto = _crypto(holdings, ledger, today)
    limit_private = PRIVATE_SALES_LIMIT if today.year >= 2024 else 600.0

    personal = None
    if other_income is not None:
        k = max(taxable - full_allowance, 0.0)
        base = float(other_income)
        extra = income_tax(base + k, today.year, joint) - income_tax(base, today.year, joint)
        personal_total = extra * (1 + church)
        flat_total = k * rate
        basic = TARIFFS[tariff_year(today.year)]["basic"] * (2 if joint else 1)
        personal = dict(
            taxable_capital=round(k, 2), flat_tax=round(flat_total, 2), personal_tax=round(personal_total, 2),
            saving=round(max(flat_total - personal_total, 0.0), 2),
            personal_rate_pct=round(extra / k * 100, 1) if k else None,
            nv_possible=base + k <= basic, basic_allowance=basic, headroom=round(basic - base - k, 2),
        )

    tips = []
    if personal is None:
        tips.append({"code": "enter_income"})
    elif personal["nv_possible"]:
        tips.append({"code": "nv", "amount": round(cur["withheld"], 2)})
    elif personal["saving"] >= 1:
        tips.append({"code": "guenstiger", "amount": personal["saving"]})
    if benefit >= MIN_BENEFIT and not (personal and personal["nv_possible"]):
        tips.append({"code": "reset", "amount": round(left, 2), "benefit": round(benefit, 2)})
    if losses and losses[0]["saves_now"] >= MIN_BENEFIT and not (personal and (personal["nv_possible"] or personal["saving"] >= 1)):
        tips.append({"code": "losses", "amount": losses[0]["saves_now"]})
    if pot_stock > 0:
        tips.append({"code": "stock_pot", "amount": round(pot_stock, 2)})
    if (pot_stock > 0 or pot_general > 0) and today.month >= 10:
        tips.append({"code": "loss_certificate"})
    if fsa < full_allowance and cur["withheld"] > 0:
        tips.append({"code": "fsa", "amount": fsa, "limit": full_allowance})
    for c in crypto:
        if c["next_tax_free"]:
            tips.append({"code": "crypto_free", "name": c["name"], "date": c["next_tax_free"]})
    if cur["private_sales"]:
        tips.append({"code": "crypto_limit", "amount": round(cur["private_sales"], 2), "limit": limit_private,
                     "over": cur["private_sales"] >= limit_private})
    rewards = cur["excluded"].get("Crypto rewards", 0.0)
    if rewards:
        tips.append({"code": "crypto_rewards", "amount": round(rewards, 2), "limit": OTHER_INCOME_LIMIT})
    if today.month >= 10 and any(h["asset_class"] == "FUND" for h in holdings):
        tips.append({"code": "vorabpauschale"})

    return dict(
        year=today.year, tariff_year=tariff_year(today.year), allowance=fsa, full_allowance=full_allowance,
        income_ytd=round(cur["income"], 2), realized_ytd=round(cur["realized"], 2),
        taxable_ytd=round(taxable_ytd, 2), expected_rest=round(rest, 2), taxable_expected=round(taxable, 2),
        allowance_used=round(used, 2), allowance_left=round(left, 2), reset_benefit=round(benefit, 2),
        withheld_ytd=round(cur["withheld"], 2), tax_expected=round(max(taxable - fsa, 0.0) * rate, 2),
        loss_pot_stock=round(pot_stock, 2), loss_pot_general=round(pot_general, 2),
        private_sales_ytd=round(cur["private_sales"], 2), private_sales_limit=limit_private,
        excluded={k: round(v, 2) for k, v in cur["excluded"].items()},
        reset=reset, losses=losses, crypto=crypto, personal=personal, tips=tips, history=history[-5:],
    )
