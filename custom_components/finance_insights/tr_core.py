"""Pure-Python analysis core for Trade Republic transaction data.

No third-party dependencies, so the same file runs in the CLI and inside
Home Assistant. Two input adapters produce one normalized row format:

* `read_tr_csv`   - the CSV export from the Trade Republic app/web
* `rows_from_pytr` - raw timeline events fetched with pytr

`analyze(rows, prices)` returns a JSON-serializable dict.
"""
from __future__ import annotations

import csv
import io
import re
from collections import defaultdict
from datetime import date, timedelta, timezone

EPS = 1e-9

DEPOSIT = {"CUSTOMER_INBOUND", "CUSTOMER_INPAYMENT", "TRANSFER_INBOUND", "TRANSFER_INSTANT_INBOUND"}
WITHDRAWAL = {"CUSTOMER_OUTBOUND_REQUEST", "TRANSFER_OUTBOUND", "TRANSFER_INSTANT_OUTBOUND"}
# Trade Republic labels SEPA direct debits it pays out as "..._DIRECT_DEBIT_INBOUND".
SPENDING = {"CARD_TRANSACTION", "CARD_TRANSACTION_INTERNATIONAL", "TRANSFER_DIRECT_DEBIT_INBOUND",
            "CARD_ORDERING_FEE"}

MCC = {
    4111: "Transport", 4121: "Transport", 4131: "Transport", 4789: "Transport",
    4511: "Travel", 4722: "Travel", 7011: "Travel",
    4814: "Phone and internet", 4899: "Streaming and media", 4900: "Utilities",
    5311: "Department stores", 5331: "General merchandise", 5399: "General merchandise",
    5411: "Groceries", 5422: "Groceries", 5441: "Groceries", 5451: "Groceries", 5499: "Groceries",
    5462: "Bakeries", 5541: "Fuel", 5542: "Fuel",
    5651: "Clothing", 5655: "Clothing", 5661: "Clothing", 5691: "Clothing", 5699: "Clothing",
    5712: "Home and furniture", 5719: "Home and furniture", 5732: "Electronics",
    5734: "Software and subscriptions", 5735: "Streaming and media",
    5812: "Restaurants", 5813: "Bars", 5814: "Fast food",
    5815: "Digital goods", 5816: "Games", 5817: "Digital goods", 5818: "Digital goods",
    5912: "Pharmacy", 5921: "Liquor stores", 5941: "Sports", 5942: "Books", 5945: "Hobby and toys",
    5977: "Beauty", 7230: "Beauty", 5999: "Online and misc. retail",
    7832: "Cinema", 7997: "Clubs and recreation", 7999: "Recreation", 8999: "Professional services",
}

# Merchants that show up under several card descriptors.
MERCHANT_ALIASES = [(re.compile(r"\bAMZN\b|AMAZON"), "AMAZON")]


# ---------------------------------------------------------------- helpers

def num(x):
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def z(x):
    return x or 0.0


def mcc_category(code, kind):
    if kind == "TRANSFER_DIRECT_DEBIT_INBOUND":
        return "Direct debits"
    if kind == "CARD_ORDERING_FEE":
        return "Card fees"
    if kind == "GIFT":
        return "Gifts sent"
    if code is None:
        return "Refunds and other" if kind.startswith("CARD") else "Uncategorized"
    code = int(code)
    if code in MCC:
        return MCC[code]
    if 3000 <= code <= 3999:
        return "Travel"
    return f"MCC {code}"


def merchant(name):
    if not name or not str(name).strip():
        return "(no merchant name)"
    base = str(name).split("*")[0].strip().upper()
    for rx, alias in MERCHANT_ALIASES:
        if rx.search(base):
            return alias
    parts = [p for p in base.split() if not re.fullmatch(r"[\d\-/]{4,}", p)]
    if len(parts) == 2 and parts[0] == parts[1]:
        parts = parts[:1]
    return " ".join(parts) or base


def classify(r):
    t, cat = r["type"], r["category"]
    if cat == "TRADING" or t in ("BUY", "SELL"):
        return "trade", None
    if t == "FREE_RECEIPT":
        return "income", "Crypto rewards"
    if cat in ("CORPORATE_ACTION", "DELIVERY"):
        return "corporate", None
    if t in DEPOSIT:
        return "deposit", None
    if t in WITHDRAWAL:
        return "withdrawal", None
    if t in SPENDING:
        return "spending", None
    if t == "GIFT":
        return ("income", "Bonuses and gifts") if z(r["amount"]) > 0 else ("spending", None)
    if t == "DIVIDEND":
        return "income", "Dividends"
    if t == "INTEREST_PAYMENT":
        return "income", ("Bond coupons" if r["symbol"] else "Cash interest")
    if t == "BENEFITS_SAVEBACK":
        return "income", "Saveback"
    if t == "STOCKPERK":
        return "income", "Stock perks"
    if t in ("TAX_OPTIMIZATION", "TAX"):
        return "tax", None
    return "other", None


def _finish(row):
    row["bucket"], row["income_kind"] = classify(row)
    row["cash"] = z(row["amount"]) + z(row["fee"]) + z(row["tax"])
    if row["type"] == "FREE_RECEIPT":
        row["income_value"] = z(row["shares"]) * z(row["price"])
    elif row["bucket"] == "income":
        row["income_value"] = z(row["amount"])
    else:
        row["income_value"] = 0.0
    row["month"] = row["date"][:7]
    row["year"] = int(row["date"][:4])
    return row


# ---------------------------------------------------------------- adapters

def read_tr_csv(source):
    """Parse the Trade Republic CSV export. `source` is a path or CSV text."""
    if isinstance(source, str) and "\n" not in source:
        with open(source, newline="", encoding="utf-8-sig") as fh:
            text = fh.read()
    else:
        text = source
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        mcc = num(r.get("mcc_code"))
        rows.append(_finish(dict(
            datetime=r["datetime"], date=r["date"], type=r["type"], category=r["category"],
            asset_class=r.get("asset_class") or None, name=r.get("name") or None,
            symbol=r.get("symbol") or None, shares=num(r.get("shares")), price=num(r.get("price")),
            amount=num(r.get("amount")), fee=num(r.get("fee")), tax=num(r.get("tax")),
            mcc=int(mcc) if mcc is not None else None, description=r.get("description") or "",
            id=r.get("transaction_id"), source="csv",
        )))
    rows.sort(key=lambda x: x["datetime"])
    return rows


def rows_from_pytr(raw_events):
    """Convert raw pytr timeline events (dicts) to normalized rows.

    pytr reports trade totals including fees and taxes as positive numbers,
    so they are split back out here. Card spending has no MCC code in the
    timeline and lands in "Card (timeline)".
    """
    from pytr.event import ConditionalEventType, Event, PPEventType  # optional dependency

    rows = []
    for raw in raw_events:
        try:
            ev = Event.from_dict(raw)
        except Exception:  # noqa: BLE001 - one malformed event must not stop the sync
            continue
        if ev.event_type is None:
            continue
        et = ev.event_type
        raw_type = (raw.get("eventType") or "").upper()
        dt = ev.date.astimezone(timezone.utc)
        base = dict(datetime=dt.isoformat().replace("+00:00", "Z"), date=dt.date().isoformat(),
                    asset_class=None, name=ev.title, symbol=ev.isin, shares=None, price=None,
                    amount=None, fee=None, tax=None, mcc=None, description=raw.get("subtitle") or "",
                    id=raw.get("id"), source="pytr")
        value, fees, taxes, shares = ev.value, z(ev.fees), z(ev.taxes), ev.shares

        def add(_base=base, **kw):
            r = dict(_base)
            r.update(kw)
            rows.append(_finish(r))

        if et == ConditionalEventType.TRADE_INVOICE and value is not None:
            if ev.shares2 and ev.isin2:  # swap-like trade: ignore the cash leg, move shares
                add(category="CORPORATE_ACTION", type="SWAP", symbol=ev.isin, shares=-z(shares))
                add(category="CORPORATE_ACTION", type="SWAP", symbol=ev.isin2, shares=z(ev.shares2))
                continue
            if value < 0:
                gross = value + fees
                add(category="TRADING", type="BUY", shares=z(shares), amount=gross, fee=-fees or None,
                    price=(-gross / shares) if shares else None)
            else:
                gross = value + fees + taxes
                add(category="TRADING", type="SELL", shares=-z(shares), amount=gross, fee=-fees or None,
                    tax=-taxes or None, price=(gross / shares) if shares else None)
        elif et == ConditionalEventType.SAVEBACK and value is not None:
            add(category="CASH", type="BENEFITS_SAVEBACK", amount=-value)
            add(category="TRADING", type="BUY", shares=z(shares), amount=value,
                price=(-value / shares) if shares else None)
        elif et == ConditionalEventType.PRIVATE_MARKETS_ORDER and value is not None:
            kind = "BUY" if value < 0 else "SELL"
            add(category="TRADING", type=kind, shares=z(shares) if kind == "BUY" else -z(shares),
                amount=value + fees, fee=-fees or None)
        elif et == PPEventType.DIVIDEND:
            add(category="CASH", type="DIVIDEND", amount=z(value) + taxes, tax=-taxes or None, shares=shares)
        elif et == PPEventType.INTEREST:
            add(category="CASH", type="INTEREST_PAYMENT", amount=z(value) + taxes, tax=-taxes or None)
        elif et == PPEventType.DEPOSIT:
            if raw_type.startswith("CARD"):
                add(category="CASH", type="CARD_TRANSACTION", amount=value, name=None)
            else:
                add(category="CASH", type="TRANSFER_INBOUND", amount=value)
        elif et == PPEventType.REMOVAL:
            if raw_type.startswith("CARD") or (ev.note or "").startswith("card"):
                add(category="CASH", type="CARD_TRANSACTION", amount=value)
            else:
                add(category="CASH", type="TRANSFER_OUTBOUND", amount=value)
        elif et in (PPEventType.TAXES, PPEventType.TAX_REFUND):
            add(category="CASH", type="TAX", amount=0.0, tax=value)
        elif et == PPEventType.SPINOFF:
            add(category="CORPORATE_ACTION", type="SPIN_OFF", symbol=ev.isin,
                shares=z(ev.shares2 if ev.shares2 else shares))
        elif et == PPEventType.SWAP:
            add(category="CORPORATE_ACTION", type="SWAP", symbol=ev.isin, shares=-z(shares))
            if ev.isin2:
                add(category="CORPORATE_ACTION", type="SWAP", symbol=ev.isin2, shares=z(ev.shares2))
        elif et in (PPEventType.SPLIT, PPEventType.TRANSFER_IN):
            add(category="DELIVERY", type="FREE_RECEIPT" if et == PPEventType.TRANSFER_IN else "SPLIT",
                shares=z(shares), price=0.0)
        elif et == PPEventType.TRANSFER_OUT:
            add(category="CORPORATE_ACTION", type="TRANSFER_OUT", shares=-z(shares))
        else:
            add(category="CASH", type=str(et.value), amount=value)
    rows.sort(key=lambda x: x["datetime"])
    return rows


def merge_rows(csv_rows, live_rows):
    """CSV history first; live rows only after the newest CSV timestamp."""
    if not csv_rows:
        return list(live_rows)
    cutoff = max(r["datetime"] for r in csv_rows)
    return csv_rows + [r for r in live_rows if r["datetime"] > cutoff]


def read_bonds_csv(source):
    """isin,coupon,maturity,frequency CSV. Coupon in percent, maturity YYYY-MM-DD,
    frequency = payments per year."""
    if isinstance(source, str) and "\n" not in source:
        with open(source, newline="", encoding="utf-8-sig") as fh:
            source = fh.read()
    out = {}
    for r in csv.DictReader(io.StringIO(source)):
        isin = (r.get("isin") or r.get("symbol") or "").strip()
        coupon = num((r.get("coupon") or "").replace(",", "."))
        if isin and coupon is not None and r.get("maturity"):
            out[isin] = dict(coupon=coupon, maturity=r["maturity"].strip(), frequency=int(num(r.get("frequency")) or 1))
    return out


def read_prices_csv(source):
    """symbol,price CSV. EUR; bonds in percent of nominal."""
    if isinstance(source, str) and "\n" not in source:
        with open(source, newline="", encoding="utf-8-sig") as fh:
            source = fh.read()
    out = {}
    for r in csv.DictReader(io.StringIO(source)):
        p = num((r.get("price") or "").replace(",", ".")) if isinstance(r.get("price"), str) else num(r.get("price"))
        if r.get("symbol") and p is not None:
            out[r["symbol"].strip()] = p
    return out


# ---------------------------------------------------------------- ledger

class Ledger:
    """FIFO ledger, the method Trade Republic and German tax statements use.
    Buy fees go into the cost basis, sell fees reduce proceeds, and taxes are
    reported separately."""

    def __init__(self):
        self.pos = {}
        self.realized = []
        self.warnings = []

    def p(self, row):
        sym = row["symbol"]
        if sym not in self.pos:
            self.pos[sym] = dict(symbol=sym, name=row["name"] or sym, asset_class=row["asset_class"],
                                 shares=0.0, cost=0.0, lots=[], last_price=None, last_date=None, desc="")
        q = self.pos[sym]
        if row["asset_class"] and not q["asset_class"]:
            q["asset_class"] = row["asset_class"]
        return q

    @staticmethod
    def _add(q, shares, cost, day=None):
        """Lots are [shares, cost per share, acquisition date]. The date matters for crypto holding periods."""
        if shares > EPS:
            q["lots"].append([shares, cost / shares, day])
        q["shares"] += shares
        q["cost"] += cost

    @staticmethod
    def _take(q, qty):
        """Remove `qty` shares oldest lot first; return their cost basis and the lots taken."""
        basis, left, taken = 0.0, qty, []
        while left > EPS and q["lots"]:
            lot = q["lots"][0]
            n = min(left, lot[0])
            basis += n * lot[1]
            taken.append([n, lot[1], lot[2]])
            lot[0] -= n
            left -= n
            if lot[0] <= 1e-9:
                q["lots"].pop(0)
        q["shares"] = max(0.0, q["shares"] - qty)
        q["cost"] = sum(lot[0] * lot[1] for lot in q["lots"]) if q["shares"] > 1e-9 else 0.0
        if q["shares"] <= 1e-9:
            q["lots"] = []
        return basis, taken

    def _price(self, q, row):
        if z(row["price"]) > 0:
            q["last_price"], q["last_date"] = row["price"], row["date"]

    def buy(self, row):
        q = self.p(row)
        self._add(q, z(row["shares"]), -z(row["amount"]) - z(row["fee"]), row["date"])
        if row["name"]:
            q["name"] = row["name"]
        if row["asset_class"] == "BOND" and row["description"]:
            q["desc"] = row["description"]
        self._price(q, row)

    def sell(self, row):
        q = self.p(row)
        qty = -z(row["shares"])
        if qty > q["shares"] + 1e-6:
            self.warnings.append(f"{row['date']}: sold {qty:g} {q['name']} but ledger held {q['shares']:g}")
        basis, taken = self._take(q, qty)
        proceeds = z(row["amount"]) + z(row["fee"])
        self._price(q, row)
        self.realized.append(dict(date=row["date"], year=row["year"], symbol=q["symbol"], name=q["name"],
                                  asset_class=q["asset_class"], shares=qty, proceeds=proceeds,
                                  basis=basis, gain=proceeds - basis, tax=z(row["tax"]), lots=taken))

    def receive(self, row, cost):
        q = self.p(row)
        self._add(q, z(row["shares"]), cost, row["date"])
        self._price(q, row)

    def corporate(self, group):
        out = [r for r in group if z(r["shares"]) < 0]
        inc = [r for r in group if z(r["shares"]) > 0]
        moved, old_price, ratio_out, taken = 0.0, None, 0.0, []
        for r in out:
            q = self.p(r)
            basis, lots = self._take(q, -z(r["shares"]))
            moved += basis
            taken += lots
            old_price = q["last_price"]
            ratio_out += -z(r["shares"])
        for r in inc:
            q = self.p(r)
            if out:
                if old_price and q["last_price"] is None and len(out) == 1 and len(inc) == 1:
                    # Carry the pre-split price over at the split ratio (stale estimate).
                    q["last_price"], q["last_date"] = old_price * ratio_out / z(r["shares"]), r["date"]
            if len(out) == 1 and len(inc) == 1 and taken and ratio_out > EPS:
                # Split or ISIN change: keep acquisition dates, scale the share counts.
                factor = z(r["shares"]) / ratio_out
                for n, c, day in taken:
                    self._add(q, n * factor, n * c, day)
            else:
                self._add(q, z(r["shares"]), moved / len(inc) if out else 0.0, r["date"])
            if r["name"]:
                q["name"] = r["name"]
        if out and not inc and group[0]["type"] != "TRANSFER_OUT":
            self.warnings.append(f"{group[0]['date']}: {group[0]['type']} removed shares without a replacement")

    def run(self, rows):
        pending = []
        for row in rows:
            if pending and (row["datetime"] != pending[0]["datetime"] or row["bucket"] != "corporate"):
                self.corporate(pending)
                pending = []
            if not row["symbol"]:
                continue
            if row["bucket"] == "trade":
                (self.buy if row["type"] == "BUY" or z(row["shares"]) > 0 else self.sell)(row)
            elif row["type"] == "FREE_RECEIPT":
                self.receive(row, row["income_value"])
            elif row["bucket"] == "corporate" and row["shares"] is not None:
                pending.append(row)
        if pending:
            self.corporate(pending)
        return self


# ---------------------------------------------------------------- analysis

def _sum_by(items, key, val):
    out = defaultdict(float)
    for it in items:
        out[key(it)] += val(it)
    return dict(out)


def _round(obj):
    if isinstance(obj, float):
        return round(obj, 4)
    if isinstance(obj, dict):
        return {k: _round(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round(v) for v in obj]
    return obj


def holdings(ledger, prices=None, live_positions=None):
    """Open positions valued with (in order) live TR prices, manual prices,
    or the last trade price in the data."""
    prices = prices or {}
    live = {p["isin"]: p for p in (live_positions or [])}
    out = []
    for q in ledger.pos.values():
        if q["shares"] <= 1e-6 and q["symbol"] not in live:
            continue
        bond = q["asset_class"] == "BOND"
        unit = 100.0 if bond else 1.0
        shares, cost = q["shares"], q["cost"]
        if q["symbol"] in live:
            lp = live[q["symbol"]]
            price, source = float(lp["price"]), "live"
            if lp.get("shares") is not None and abs(float(lp["shares"]) - shares) > 1e-4:
                ledger.warnings.append(f"{q['name']}: ledger has {shares:g}, Trade Republic reports "
                                       f"{float(lp['shares']):g}; using Trade Republic figures")
                shares = float(lp["shares"])
                if lp.get("avg_cost") is not None:
                    cost = float(lp["avg_cost"]) * shares
        elif q["symbol"] in prices:
            price, source = prices[q["symbol"]] / unit, "manual"
        elif q["last_price"]:
            price, source = q["last_price"], f"last trade {q['last_date']}"
        else:
            price, source = None, "no price"
        if shares <= 1e-6:
            continue
        value = shares * price if price is not None else None
        name = q["name"]
        if bond and q["desc"]:
            issuer = q["desc"].split(q["symbol"], 1)[-1].split(",")[0].strip()
            name = f"{issuer} ({q['name']})"
        out.append(dict(
            symbol=q["symbol"], name=name, asset_class=q["asset_class"] or "OTHER", shares=shares,
            avg_cost=cost / shares * unit, cost=cost, price=price * unit if price is not None else None,
            price_unit="%" if bond else "EUR", price_source=source, value=value,
            unrealized=value - cost if value is not None else None,
            unrealized_pct=(value / cost - 1) * 100 if value is not None and cost > EPS else None,
        ))
    total = sum(h["value"] or 0 for h in out)
    for h in out:
        h["weight_pct"] = (h["value"] or 0) / total * 100 if total > EPS else 0.0
    out.sort(key=lambda h: -(h["value"] or 0))
    return out



# ---------------------------------------------------------------- fixed income

# Terms for bonds that the CSV does not carry (coupon, maturity, payments per
# year). Supplied per ISIN through `bond_terms`, for example from bonds.csv.
KNOWN_BONDS: dict[str, dict] = {}


def _xirr(flows):
    """Annualized internal rate of return for [(date, amount)]; None if no sign change."""
    if not flows or not any(v < 0 for _, v in flows) or not any(v > 0 for _, v in flows):
        return None
    t0 = min(d for d, _ in flows)

    def npv(r):
        return sum(v / (1 + r) ** ((d - t0).days / 365.0) for d, v in flows)

    lo, hi = -0.99, 10.0
    if npv(lo) * npv(hi) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if npv(lo) * npv(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def _add_months(d, months):
    y, m = divmod(d.month - 1 + months, 12)
    y += d.year
    m += 1
    days = [31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return date(y, m, min(d.day, days))


def fixed_income(rows, holdings_list, bond_terms=None, today=None):
    """Hold-to-maturity view per bond: invested, coupons received and still due,
    repayment, profit, and annualized return on the buy-in. Gross, before tax,
    assumes the issuer pays in full and coupons are not reinvested."""
    today = today or date.today()
    terms = dict(KNOWN_BONDS)
    terms.update(bond_terms or {})
    out = []
    for h in holdings_list:
        if h["asset_class"] != "BOND":
            continue
        sym = h["symbol"]
        own = [r for r in rows if r["symbol"] == sym]
        buys = [(date.fromisoformat(r["date"]), z(r["amount"]) + z(r["fee"])) for r in own
                if r["bucket"] == "trade" and z(r["shares"]) > 0]
        coupons = [r for r in own if r["type"] == "INTEREST_PAYMENT"]
        received = sum(z(r["amount"]) for r in coupons)
        reversed_coupon = any(z(r["amount"]) < 0 for r in coupons)
        t = terms.get(sym) or {}
        price_pct = h["price"]
        item = dict(symbol=sym, name=h["name"], face=h["shares"], invested=h["cost"], market_value=h["value"],
                    price_pct=price_pct, coupons_received=received, status="ok", coupon_missed=reversed_coupon, market_yield=None,
                    coupon=t.get("coupon"), maturity=t.get("maturity"), frequency=t.get("frequency"),
                    coupons_due=None, coupons_due_count=None, next_coupon=None, repayment=h["shares"],
                    profit_to_maturity=None, return_pa=None, years_left=None)
        if t.get("coupon") is not None and t.get("maturity"):
            maturity = date.fromisoformat(t["maturity"])
            freq = int(t.get("frequency") or 1)
            step = 12 // freq
            per = h["shares"] * t["coupon"] / 100 / freq
            dates, d, i = [], maturity, 0
            while d > today:
                dates.append(d)
                i += 1
                d = _add_months(maturity, -step * i)
            dates.sort()
            due = per * len(dates)
            flows = buys + [(date.fromisoformat(r["date"]), z(r["amount"])) for r in coupons]
            flows += [(dd, per) for dd in dates] + [(maturity, h["shares"])]
            irr = _xirr(flows)
            if h["value"]:
                my = _xirr([(today, -h["value"])] + [(dd, per) for dd in dates] + [(maturity, h["shares"])])
                item["market_yield"] = my * 100 if my is not None else None
            item.update(coupons_due=due, coupons_due_count=len(dates), next_coupon=dates[0].isoformat() if dates else None,
                        profit_to_maturity=received + due + h["shares"] - h["cost"],
                        return_pa=irr * 100 if irr is not None else None,
                        years_left=max(0.0, (maturity - today).days / 365.0))
        # A missed coupon or a yield far above normal levels means the market doubts repayment.
        my = item["market_yield"]
        if reversed_coupon or (my is not None and my > 25) or (price_pct is not None and price_pct < 40):
            item["status"] = "distressed"
        elif my is not None and my > 12:
            item["status"] = "watch"
        out.append(item)
    out.sort(key=lambda b: -(b["invested"] or 0))
    return out


def _add_dividends(hold, rows, today):
    """Gross dividends per open position: all time and the last 12 months, plus
    the return including dividends."""
    cutoff = (today - timedelta(days=365)).isoformat()
    for h in hold:
        divs = [r for r in rows if r["symbol"] == h["symbol"] and r["type"] == "DIVIDEND"]
        h["dividends"] = sum(z(r["amount"]) for r in divs)
        h["dividends_tax"] = sum(z(r["tax"]) for r in divs)
        h["dividends_12m"] = sum(z(r["amount"]) for r in divs if r["date"] > cutoff)
        h["dividend_count"] = len(divs)
        h["last_dividend"] = max((r["date"] for r in divs), default=None)
        if h["unrealized"] is not None:
            h["return_incl_dividends"] = h["unrealized"] + h["dividends"]
            h["return_incl_dividends_pct"] = h["return_incl_dividends"] / h["cost"] * 100 if h["cost"] > EPS else None
        else:
            h["return_incl_dividends"] = h["return_incl_dividends_pct"] = None


def analyze(rows, prices=None, live_positions=None, live_cash=None, today=None, bond_terms=None):
    today = today or date.today()
    ledger = Ledger().run(rows)
    hold = holdings(ledger, prices, live_positions)
    warnings = ledger.warnings
    _add_dividends(hold, rows, today)

    trades = [r for r in rows if r["bucket"] == "trade"]
    income = [r for r in rows if r["bucket"] == "income"]
    spend = []
    for r in rows:
        if r["bucket"] == "spending":
            spend.append(dict(date=r["date"], month=r["month"], year=r["year"],
                              value=-(z(r["amount"]) + z(r["fee"])), merchant=merchant(r["name"]),
                              category=mcc_category(r["mcc"], r["type"]) if r["source"] == "csv"
                              else ("Card (timeline)" if r["type"].startswith("CARD") else "Uncategorized")))
    other = [r for r in rows if r["bucket"] == "other"]
    for t, n in sorted(_sum_by(other, lambda r: r["type"], lambda r: 1).items()):
        warnings.append(f"unclassified type {t}: {int(n)} rows, counted in the cash balance only")

    deposits = sum(z(r["amount"]) for r in rows if r["bucket"] == "deposit")
    withdrawals = -sum(z(r["amount"]) for r in rows if r["bucket"] == "withdrawal")
    spending = sum(s["value"] for s in spend)
    cash = sum(r["cash"] for r in rows)
    value = sum(h["value"] or 0 for h in hold)
    cost = sum(h["cost"] for h in hold)
    unpriced_cost = sum(h["cost"] for h in hold if h["value"] is None)
    income_total = sum(r["income_value"] for r in income)
    taxes = sum(z(r["tax"]) for r in rows)
    realized_total = sum(x["gain"] for x in ledger.realized)
    unrealized = value - (cost - unpriced_cost)
    net_contrib = deposits - withdrawals - spending

    ym, y = today.strftime("%Y-%m"), today.year
    # Rolling windows, so a monthly savings plan or a quarterly dividend is never half counted.
    since_30d, since_60d = (today - timedelta(days=30)).isoformat(), (today - timedelta(days=60)).isoformat()
    since_12m = (today - timedelta(days=365)).isoformat()
    prev_month = (date(y, today.month, 1) - timedelta(days=1)).strftime("%Y-%m")

    summary = dict(
        first_date=rows[0]["date"] if rows else None, last_date=rows[-1]["date"] if rows else None,
        transactions=len(rows), deposits=deposits, withdrawals=withdrawals, spending=spending,
        net_contributions=net_contrib, cash=live_cash if live_cash is not None else cash,
        cash_derived=cash, holdings_cost=cost, holdings_value=value, net_worth=(live_cash if live_cash
        is not None else cash) + value, realized=realized_total, unrealized=unrealized,
        income=income_total, taxes=taxes, trade_fees=sum(z(r["fee"]) for r in trades),
        total_return=realized_total + unrealized + income_total + taxes + sum(r["cash"] for r in other),
        realized_ytd=sum(x["gain"] for x in ledger.realized if x["year"] == y),
        income_ytd=sum(r["income_value"] for r in income if r["year"] == y),
        dividends_ytd=sum(r["income_value"] for r in income if r["year"] == y and r["income_kind"] == "Dividends"),
        taxes_ytd=sum(z(r["tax"]) for r in rows if r["year"] == y),
        # How much of a year the export covers, so an average is not diluted by empty months.
        months_12m=round(min(12.0, max(1.0, (today - date.fromisoformat(rows[0]["date"])).days / 30.44)), 2) if rows else 12.0,
        spending_30d=sum(s["value"] for s in spend if s["date"] > since_30d),
        spending_prev_30d=sum(s["value"] for s in spend if since_60d < s["date"] <= since_30d),
        income_30d=sum(r["income_value"] for r in income if r["date"] > since_30d),
        income_prev_30d=sum(r["income_value"] for r in income if since_60d < r["date"] <= since_30d),
        spending_month=sum(s["value"] for s in spend if s["month"] == ym),
        spending_prev_month=sum(s["value"] for s in spend if s["month"] == prev_month),
        spending_ytd=sum(s["value"] for s in spend if s["year"] == y),
        positions=len(hold),
    )

    months = sorted({r["month"] for r in rows})
    monthly = []
    for m in months:
        rs = [r for r in rows if r["month"] == m]
        monthly.append(dict(
            month=m,
            deposits=sum(z(r["amount"]) for r in rs if r["bucket"] == "deposit"),
            top_ups=sum(z(r["amount"]) for r in rs if r["bucket"] == "deposit" and r["type"] == "CUSTOMER_INPAYMENT"),
            transfers_in=sum(z(r["amount"]) for r in rs if r["bucket"] == "deposit" and r["type"] != "CUSTOMER_INPAYMENT"),
            withdrawals=-sum(z(r["amount"]) for r in rs if r["bucket"] == "withdrawal"),
            spending=sum(s["value"] for s in spend if s["month"] == m),
            bought=-sum(z(r["amount"]) for r in rs if r["bucket"] == "trade" and z(r["shares"]) > 0),
            sold=sum(z(r["amount"]) for r in rs if r["bucket"] == "trade" and z(r["shares"]) < 0),
            income=sum(r["income_value"] for r in rs if r["bucket"] == "income"),
            realized=sum(x["gain"] for x in ledger.realized if x["date"][:7] == m),
            taxes=sum(z(r["tax"]) for r in rs),
        ))

    by_pos = defaultdict(lambda: dict(sells=0, proceeds=0.0, gain=0.0, tax=0.0))
    for x in ledger.realized:
        b = by_pos[x["symbol"]]
        b.update(name=x["name"], asset_class=x["asset_class"], symbol=x["symbol"])
        b["sells"] += 1
        b["proceeds"] += x["proceeds"]
        b["gain"] += x["gain"]
        b["tax"] += x["tax"]

    merchants = defaultdict(lambda: dict(value=0.0, count=0))
    for s in spend:
        merchants[s["merchant"]]["value"] += s["value"]
        merchants[s["merchant"]]["count"] += 1

    result = dict(
        summary=summary,
        holdings=hold,
        realized=[{k: v for k, v in x.items() if k != "lots"} for x in ledger.realized],
        realized_by_position=sorted(by_pos.values(), key=lambda b: b["gain"]),
        realized_by_year=_sum_by(ledger.realized, lambda x: str(x["year"]), lambda x: x["gain"]),
        income=[dict(date=r["date"], kind=r["income_kind"], name=r["name"], value=r["income_value"],
                     tax=z(r["tax"])) for r in income],
        income_by_year_kind={str(yr): _sum_by([r for r in income if r["year"] == yr],
                                              lambda r: r["income_kind"], lambda r: r["income_value"])
                             for yr in sorted({r["year"] for r in income})},
        # Rolling twelve months, so the income view matches the spending view next to it.
        income_kinds_12m=dict(sorted(_sum_by([r for r in income if r["date"] > since_12m],
                                             lambda r: r["income_kind"], lambda r: r["income_value"]).items(),
                                     key=lambda kv: -kv[1])),
        income_sources_12m=sorted(
            ({"name": k, "value": round(v, 2)} for k, v in _sum_by(
                [r for r in income if r["date"] > since_12m and r["name"]],
                lambda r: r["name"], lambda r: r["income_value"]).items() if round(v, 2) != 0),
            key=lambda s: -s["value"])[:15],
        spending=spend,
        spending_by_category=[dict(category=k, value=v) for k, v in sorted(
            _sum_by(spend, lambda s: s["category"], lambda s: s["value"]).items(), key=lambda kv: -kv[1])],
        top_merchants=sorted(({"merchant": k, **v} for k, v in merchants.items()), key=lambda m: -m["value"]),
        monthly=monthly,
        fixed_income=fixed_income(rows, hold, bond_terms, today),
        warnings=warnings,
    )
    return _round(result)
