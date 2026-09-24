"""Net, VAT, and profit for a business account.

A bank booking carries an amount, a payee, and a purpose. It does not carry a VAT rate,
so the rate comes from the user's own rules. A booking no rule matches is reported as
unassigned rather than guessed, because a wrong rate here would end up in a VAT return.

Everything is taken from the day the money moved, which is Ist-Versteuerung (§20 UStG).
For anyone taxed by invoice date these figures are in the wrong period.
"""
from __future__ import annotations

import csv
import io
import re
from collections import defaultdict
from datetime import date

FIELDS = ("revenue_gross", "revenue_net", "vat_collected", "expenses_gross", "expenses_net",
          "input_vat", "unassigned_income", "unassigned_expense")


def read_vat_rules(data: bytes | str) -> list[tuple[re.Pattern, float]]:
    """pattern,vat from the rules file. A row without a vat column is a category rule only."""
    if isinstance(data, bytes):
        data = data.decode("utf-8-sig", errors="replace")
    rules = []
    for row in csv.DictReader(io.StringIO(data)):
        pattern, rate = (row.get("pattern") or "").strip(), (row.get("vat") or "").strip()
        if not pattern or not rate:
            continue
        try:
            rules.append((re.compile(pattern, re.IGNORECASE), float(rate.replace("%", "").replace(",", "."))))
        except (re.error, ValueError):
            continue
    return rules


def rate_of(row: dict, rules: list[tuple[re.Pattern, float]], default: float | None) -> float | None:
    """The VAT rate for one booking, or None when nothing says what it is."""
    text = f"{row.get('booking_text') or ''} {row.get('purpose') or ''} {row.get('counterparty') or ''}"
    for pattern, rate in rules:
        if pattern.search(text):
            return rate
    return default


def split(gross: float, rate: float) -> tuple[float, float]:
    """Gross to net and VAT. The rate is a percentage, so 19 means 19 %."""
    net = gross / (1 + rate / 100) if rate else gross
    return net, gross - net


def _quarter(month: str) -> str:
    return f"{month[:4]}-Q{(int(month[5:7]) - 1) // 3 + 1}"


def _totals() -> dict:
    return dict.fromkeys(FIELDS, 0.0)


def _finish(totals: dict) -> dict:
    out = {k: round(v, 2) for k, v in totals.items()}
    out["vat_due"] = round(totals["vat_collected"] - totals["input_vat"], 2)
    out["profit"] = round(totals["revenue_net"] - totals["expenses_net"], 2)
    out["unassigned"] = round(totals["unassigned_income"] + totals["unassigned_expense"], 2)
    return out


def analyze_business(rows: list[dict], today: date, *, rules=None, default_rate: float | None = None,
                     small_business: bool = False, reserve_pct: float = 0.0) -> dict:
    """rows must come from bank_core.classify(). Internal transfers are already excluded there."""
    rules = [] if small_business else list(rules or ())
    if small_business:
        default_rate = 0.0

    by_month: dict[str, dict] = defaultdict(_totals)
    by_quarter: dict[str, dict] = defaultdict(_totals)
    by_year: dict[int, dict] = defaultdict(_totals)
    open_items: dict[tuple, dict] = {}
    rate_counts: dict[str, int] = defaultdict(int)

    for row in rows:
        if row.get("pending") or row["date"] > today or row["kind"] == "internal":
            continue
        gross = abs(row["amount"])
        if not gross:
            continue
        income = row["kind"] == "income"
        rate = rate_of(row, rules, default_rate)
        buckets = (by_month[row["month"]], by_quarter[_quarter(row["month"])], by_year[row["year"]])
        if rate is None:
            key = "unassigned_income" if income else "unassigned_expense"
            for bucket in buckets:
                bucket[key] += gross
            item = open_items.setdefault((row["merchant"], row["kind"]),
                                         {"merchant": row["merchant"], "kind": row["kind"], "gross": 0.0, "count": 0})
            item["gross"] += gross
            item["count"] += 1
            continue
        rate_counts[f"{rate:g}"] += 1
        net, vat = split(gross, rate)
        for bucket in buckets:
            bucket["revenue_gross" if income else "expenses_gross"] += gross
            bucket["revenue_net" if income else "expenses_net"] += net
            bucket["vat_collected" if income else "input_vat"] += vat

    month, quarter, year = today.strftime("%Y-%m"), _quarter(today.strftime("%Y-%m")), today.year
    this_year = _finish(by_year.get(year, _totals()))
    return {
        "small_business": small_business,
        "months": [{"month": m, **_finish(t)} for m, t in sorted(by_month.items())],
        "quarters": [{"quarter": q, **_finish(t)} for q, t in sorted(by_quarter.items())],
        "years": [{"year": y, **_finish(t)} for y, t in sorted(by_year.items())],
        "month": _finish(by_month.get(month, _totals())),
        "quarter": _finish(by_quarter.get(quarter, _totals())),
        "year": this_year,
        "reserve": round(max(this_year["profit"], 0.0) * reserve_pct / 100, 2),
        "reserve_pct": reserve_pct,
        "rates": dict(sorted(rate_counts.items(), key=lambda kv: -kv[1])),
        "unassigned_items": sorted((dict(v, gross=round(v["gross"], 2)) for v in open_items.values()),
                                   key=lambda i: -i["gross"])[:20],
    }
