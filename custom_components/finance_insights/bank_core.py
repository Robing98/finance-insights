"""Pure-Python analysis for German bank accounts (Sparkasse CSV exports and FinTS).

No Home Assistant imports, so it can be tested and reused on its own.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from statistics import median, pstdev

# ---------------------------------------------------------------- parsing

_CAMT_COLUMNS = {
    "account": "Auftragskonto", "date": "Buchungstag", "value_date": "Valutadatum",
    "booking_text": "Buchungstext", "purpose": "Verwendungszweck", "creditor_id": "Glaeubiger ID",
    "mandate": "Mandatsreferenz", "e2e": "Kundenreferenz (End-to-End)",
    "counterparty": "Beguenstigter/Zahlungspflichtiger", "counterparty_iban": "Kontonummer/IBAN",
    "counterparty_bic": "BIC (SWIFT-Code)", "amount": "Betrag", "currency": "Waehrung", "info": "Info",
    "bank_category": "Kategorie",
}
# CSV-MT940 has fewer columns and the account number in "Kontonummer".
_MT940_FALLBACK = {"counterparty_iban": "Kontonummer"}


def _decode(data: bytes | str) -> str:
    if isinstance(data, str):
        return data.lstrip("﻿")
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def parse_amount(text: str | None) -> float | None:
    """German amounts: '-1.143,41' -> -1143.41. Plain '12.5' also works."""
    if text is None:
        return None
    s = str(text).strip().replace("−", "-").replace(" ", "")
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def parse_date(text: str | None) -> date | None:
    if not text:
        return None
    s = text.strip()
    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{2}|\d{4})", s)
    if m:
        d, mo, y = (int(x) for x in m.groups())
        return date(2000 + y if y < 100 else y, mo, d)
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _row_key(r: dict) -> tuple:
    return (r["account"], r["date"].isoformat(), round(r["amount"], 2), r["counterparty"].upper(),
            r["purpose"].upper()[:140], r["e2e"])


def _with_ids(rows: list[dict]) -> list[dict]:
    """Stable ids; identical rows on the same day get an occurrence number."""
    seen: Counter = Counter()
    for r in rows:
        k = _row_key(r)
        seen[k] += 1
        raw = "|".join(map(str, k)) + f"|{seen[k]}"
        r["id"] = hashlib.sha1(raw.encode()).hexdigest()[:16]
    return rows


def read_sparkasse_csv(data: bytes | str) -> list[dict]:
    """Parse a Sparkasse 'CSV-CAMT' or 'CSV-MT940' export."""
    text = _decode(data)
    sample = text[:2048]
    delimiter = ";" if sample.count(";") >= sample.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    fields = {f.strip(): f for f in (reader.fieldnames or [])}
    if "Buchungstag" not in fields or "Betrag" not in fields:
        raise ValueError("Not a Sparkasse CSV export: columns Buchungstag and Betrag are missing")
    cols = dict(_CAMT_COLUMNS)
    for key, alt in _MT940_FALLBACK.items():
        if cols[key] not in fields and alt in fields:
            cols[key] = alt
    rows = []
    for raw in reader:
        get = lambda k, raw=raw: (raw.get(fields.get(cols[k], ""), "") or "").strip()  # noqa: E731
        booked = parse_date(get("date"))
        amount = parse_amount(get("amount"))
        if booked is None or amount is None:
            continue
        info = get("info").lower()
        rows.append(dict(
            account=get("account").replace(" ", ""), date=booked, value_date=parse_date(get("value_date")) or booked,
            booking_text=get("booking_text"), purpose=re.sub(r"\s+", " ", get("purpose")),
            creditor_id=get("creditor_id"), mandate=get("mandate"), e2e="" if get("e2e") == "NOTPROVIDED" else get("e2e"),
            counterparty=re.sub(r"\s+", " ", get("counterparty")), counterparty_iban=get("counterparty_iban").replace(" ", ""),
            counterparty_bic=get("counterparty_bic").replace(" ", "").upper(), bank_category=get("bank_category"),
            amount=amount, currency=get("currency") or "EUR", pending="vorgemerkt" in info, source="csv",
        ))
    rows.sort(key=lambda r: (r["date"], r["amount"]))
    return _with_ids(rows)


def merge_exports(exports: list[list[dict]]) -> list[dict]:
    """Merge overlapping exports. A row that appears n times in one file and m times
    in another is kept max(n, m) times. Booked rows replace pending ones."""
    best: dict[tuple, list[dict]] = {}
    for rows in exports:
        groups: dict[tuple, list[dict]] = defaultdict(list)
        for r in rows:
            groups[_row_key(r)].append(r)
        for k, grp in groups.items():
            cur = best.get(k)
            booked = [r for r in grp if not r["pending"]]
            if cur is None or len(grp) > len(cur) or (booked and all(r["pending"] for r in cur)):
                best[k] = grp
    rows = [r for grp in best.values() for r in grp]
    rows.sort(key=lambda r: (r["date"], r["amount"]))
    return _with_ids(rows)


def rows_from_fints(account_iban: str, transactions: list) -> list[dict]:
    """Convert python-fints Transaction objects (mt940 or camt based) to rows."""
    rows = []
    for t in transactions:
        d = getattr(t, "data", t) or {}
        amount = d.get("amount")
        value = getattr(amount, "amount", amount)
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        booked = d.get("date") or d.get("entry_date")
        if booked is None:
            continue
        booked = booked if isinstance(booked, date) else parse_date(str(booked))
        purpose = " ".join(str(d.get(k) or "") for k in ("purpose", "additional_purpose")).strip()
        rows.append(dict(
            account=account_iban, date=booked, value_date=d.get("entry_date") or booked,
            booking_text=str(d.get("posting_text") or ""), purpose=re.sub(r"\s+", " ", purpose),
            creditor_id=str(d.get("creditor_id") or ""), mandate=str(d.get("mandate_reference") or ""),
            e2e=str(d.get("end_to_end_reference") or "").replace("NOTPROVIDED", ""),
            counterparty=re.sub(r"\s+", " ", str(d.get("applicant_name") or d.get("recipient_name") or "")),
            counterparty_iban=str(d.get("applicant_iban") or "").replace(" ", ""),
            counterparty_bic=str(d.get("applicant_bin") or "").replace(" ", "").upper(), bank_category="",
            amount=value, currency=str(d.get("currency") or "EUR"), pending=bool(d.get("pending")), source="fints",
        ))
    rows.sort(key=lambda r: (r["date"], r["amount"]))
    return _with_ids(rows)


def _dict_reader(data: bytes | str) -> csv.DictReader:
    """Comma or semicolon separated, header names case-insensitive (German Excel writes semicolons)."""
    text = _decode(data)
    first = text.splitlines()[0] if text else ""
    reader = csv.DictReader(io.StringIO(text), delimiter=";" if first.count(";") > first.count(",") else ",")
    reader.fieldnames = [(f or "").strip().lower() for f in (reader.fieldnames or [])]
    return reader


def read_balance_csv(data: bytes | str) -> dict[str, tuple[date, float]]:
    """iban,date,balance -> {iban: (date, balance)}; the newest anchor per IBAN wins."""
    out: dict[str, tuple[date, float]] = {}
    for r in _dict_reader(data):
        iban = (r.get("iban") or "").replace(" ", "")
        d, bal = parse_date(r.get("date")), parse_amount(r.get("balance"))
        if iban and d and bal is not None and (iban not in out or d >= out[iban][0]):
            out[iban] = (d, bal)
    return out


def read_rules_csv(data: bytes | str) -> list[tuple[re.Pattern, str]]:
    """pattern,category -> user rules checked before the built-in ones."""
    rules = []
    for r in _dict_reader(data):
        pat, cat = (r.get("pattern") or "").strip(), (r.get("category") or "").strip()
        if pat and cat:
            rules.append((re.compile(pat, re.IGNORECASE), cat))
    return rules


# ---------------------------------------------------------------- classification

CATEGORY_RULES: list[tuple[str, str]] = [
    ("Cash", r"GELDAUTOMAT|BARGELDAUSZAHLUNG|AUSZAHLUNG GAA|\bGAA\b|BARGELD"),
    ("Rent and housing", r"\bMIETE\b|KALTMIETE|WARMMIETE|HAUSVERWALTUNG|WOHNUNGSBAU|NEBENKOSTEN|HAUSGELD|WOHNHEIM|STUDIERENDENWERK"),
    ("Utilities", r"STADTWERKE|STROM|\bGAS\b|WASSERVERSORG|E\.ON|\bEON\b|VATTENFALL|ENBW|RUNDFUNK|BEITRAGSSERVICE|OVAG|MAINOVA"),
    ("Phone and internet", r"TELEKOM|VODAFONE|\bO2\b|TELEFONICA|1&1|1 UND 1|CONGSTAR|FREENET|UNITYMEDIA|DEUTSCHE GLASFASER"),
    ("Insurance", r"VERSICHERUNG|ALLIANZ|\bHUK\b|\bAXA\b|\bERGO\b|\bDEVK\b|R\+V|GOTHAER|CHECK24 VERS|HANSEMERKUR|LVM|SIGNAL IDUNA"),
    ("Health", r"APOTHEKE|KRANKENKASSE|\bAOK\b|TECHNIKER KRANKENKASSE|\bBARMER\b|\bDAK\b|ZAHNARZT|PRAXIS|KLINIK|OPTIK|FIELMANN|HEALTH FINANCE|\bPVS\b|ABRECHNUNGSSTELLE"),
    ("Groceries", r"\bREWE\b|EDEKA|\bALDI\b|\bLIDL\b|\bNETTO\b|\bPENNY\b|KAUFLAND|\bTEGUT\b|\bNORMA\b|GLOBUS|\bREAL\b|HIT MARKT|DENNS|ALNATURA|BAECKEREI|BÄCKEREI"),
    ("Drugstore", r"\bDM[- ]DROGERIE|\bDM FIL|ROSSMANN|MUELLER|MÜLLER DROGERIE|\bBUDNI"),
    ("Restaurants and delivery", r"LIEFERANDO|\bWOLT\b|UBER EATS|MCDONALDS|MC DONALDS|BURGER KING|STARBUCKS|RESTAURANT|PIZZ|DOMINOS|SUBWAY|KFC"),
    ("Transport", r"DB VERTRIEB|DEUTSCHE BAHN|\bRMV\b|\bVGF\b|\bBVG\b|\bMVV\b|\bHVV\b|DEUTSCHLANDTICKET|FLIXBUS|UBER\b|FREENOW|TIER\b|\bLIME\b"),
    ("Fuel and car", r"TANKSTELLE|\bARAL\b|\bSHELL\b|\bESSO\b|\bJET\b|TOTALENERGIES|\bAVIA\b|KFZ-STEUER|\bADAC\b|WERKSTATT|PARKHAUS|PARKEN"),
    ("Travel", r"LUFTHANSA|RYANAIR|EUROWINGS|BOOKING\.COM|AIRBNB|EXPEDIA|HOTEL|CONDOR|EASYJET"),
    ("Subscriptions", r"SPOTIFY|NETFLIX|DISNEY|AMAZON PRIME|PRIME VIDEO|APPLE\.COM|ITUNES|GOOGLE \*|GOOGLE PLAY|YOUTUBE|DAZN|AUDIBLE|PATREON|OPENAI|ANTHROPIC|CHATGPT|MICROSOFT|ADOBE|DISCORD|CRUNCHYROLL"),
    ("Online shopping", r"AMAZON|AMZN|ZALANDO|\bOTTO\b|EBAY|ALIEXPRESS|TEMU|SHEIN|MEDIAMARKT|SATURN|IKEA|BESTSECRET|ABOUT YOU"),
    ("Sports and leisure", r"FITNESS|MCFIT|FITX|URBAN SPORTS|KINO|CINEMA|CINESTAR|EVENTIM|TICKETMASTER|STEAM|VALVE CORP|PLAYSTATION|NINTENDO|XBOX|EPIC GAMES"),
    ("Education", r"HOCHSCHULE|UNIVERSIT|SEMESTERBEITRAG|STUDIERENDENSCHAFT|\bASTA\b|THM\b|VOLKSHOCHSCHULE|UDEMY|COURSERA"),
    ("Taxes and fees", r"FINANZAMT|STEUER|STADTKASSE|GEBUEHR|ENTGELT|KONTOFUEHRUNG|ABSCHLUSS|DISPOZINS"),
    ("Donations", r"SPENDE|DONATION|WIKIMEDIA|UNICEF|AERZTE OHNE"),
]
_COMPILED = [(cat, re.compile(p, re.IGNORECASE)) for cat, p in CATEGORY_RULES]

SPENDING_GROUPS = {
    "Housing": {"Rent and housing", "Utilities", "Phone and internet"},
    "Food and drink": {"Groceries", "Restaurants and delivery"},
    "Shopping": {"Online shopping", "Shopping", "Drugstore"},
    "Mobility and travel": {"Transport", "Fuel and car", "Travel"},
    "Subscriptions and leisure": {"Subscriptions", "Sports and leisure", "Education"},
    "Insurance and health": {"Insurance", "Health"},
    "Cash": {"Cash"},
}
GROUP_ORDER = [*SPENDING_GROUPS, "Other"]

SALARY_RX = re.compile(r"\bLOHN|GEHALT|BEZUEGE|BEZÜGE|ENTGELTABRECHNUNG|VERGUETUNG|VERGÜTUNG|\bRENTE\b|BAFOEG|BAföG|AUSBILDUNGSVERG|PRAKTIKANTEN", re.IGNORECASE)
REFUND_RX = re.compile(r"ERSTATTUNG|RUECKUEBERWEISUNG|RÜCKÜBERWEISUNG|RETOURE|RUECKZAHLUNG|RÜCKZAHLUNG|GUTSCHRIFT AUS|STORNO|REFUND", re.IGNORECASE)
INTEREST_RX = re.compile(r"ABSCHLUSS|ZINSEN|HABENZINS", re.IGNORECASE)
_WALLET_RX = re.compile(r"PAYPAL|KLARNA|AMAZON PAYMENTS|STRIPE|ADYEN|MOLLIE|SUMUP", re.IGNORECASE)
_PURCHASE_RX = re.compile(r"(?:Ihr Einkauf bei|Einkauf bei|Zahlung an)\s+([^,;/]*)", re.IGNORECASE)

DEFAULT_TRANSFER_KEYWORDS = ["TRADE REPUBLIC"]
# Brokers identified by the counterparty BIC, so transfers to your own depot count even
# when the booking only shows your own name.
BROKER_BICS = {"TRBKDEBB": "Trade Republic"}

# Categories from the bank export itself (Sparkasse "Kategorie" column), used when no rule matches.
BANK_CATEGORY_RULES: list[tuple[str, str]] = [
    ("Rent and housing", r"WOHNEN|MIETE|HAUSHALT"),
    ("Utilities", r"ENERGIE|STROM|VERSORGUNG"),
    ("Phone and internet", r"TELEKOMMUNIKATION|INTERNET|MOBILFUNK|KOMMUNIKATION"),
    ("Groceries", r"LEBENSMITTEL"),
    ("Restaurants and delivery", r"ESSEN|RESTAURANT|GASTRONOMIE"),
    ("Insurance", r"VERSICHERUNG"),
    ("Health", r"GESUNDHEIT|WELLNESS|DROGERIE|MEDIZIN"),
    ("Transport", r"MOBILIT|VERKEHR"),
    ("Fuel and car", r"AUTO|TANKEN|KFZ"),
    ("Travel", r"REISE|URLAUB"),
    ("Sports and leisure", r"FREIZEIT|UNTERHALTUNG|SPORT|HOBBY"),
    ("Education", r"BILDUNG|ERZIEHUNG"),
    ("Shopping", r"EINK(?:Ä|AE|A)UFE|SHOPPING|KLEIDUNG|ELEKTRONIK"),
    ("Cash", r"BARGELD"),
    ("Taxes and fees", r"STEUER|GEB(?:Ü|UE|U)HR"),
    ("Donations", r"SPENDE"),
    ("Subscriptions", r"\bABO"),
]
_BANK_COMPILED = [(cat, re.compile(p, re.IGNORECASE)) for cat, p in BANK_CATEGORY_RULES]
_BANK_INVESTMENT_RX = re.compile(r"GELDANLAGE|SPAREN|VERM(?:Ö|OE|O)GEN|WERTPAPIER", re.IGNORECASE)


def spending_group(category: str) -> str:
    return next((g for g, cats in SPENDING_GROUPS.items() if category in cats), "Other")


def merchant_name(row: dict) -> str:
    """Counterparty, or the shop behind PayPal and similar wallets."""
    name = row["counterparty"] or row["booking_text"] or "(unknown)"
    if _WALLET_RX.search(name):
        m = _PURCHASE_RX.search(row["purpose"])
        shop = m.group(1).strip(" .").upper() if m else ""
        return shop[:40] if shop else _WALLET_RX.search(name).group(0).upper()
    name = re.sub(r"\s+(GMBH|AG|SE|KG|E\.?K\.?|UG|MBH|& CO\.?).*$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s+\d[\d/ .-]{3,}$", "", name)
    return name.strip().upper()[:40] or "(unknown)"


def parse_offset_rules(text: str | None) -> list[tuple[re.Pattern, str]]:
    """One rule per line: 'text => category' (also ';' or '='). The text is matched literally,
    case-insensitive, against payee, purpose, and booking text."""
    rules = []
    for line in (text or "").splitlines():
        parts = re.split(r"\s*(?:=>|;|=)\s*", line.strip(), maxsplit=1)
        if len(parts) == 2 and parts[0] and parts[1]:
            rules.append((re.compile(re.escape(parts[0]), re.IGNORECASE), _category_name(parts[1])))
    return rules


def _category_name(text: str) -> str:
    """Accept any spelling of a known category, keep unknown names as typed."""
    known = {c.lower(): c for c, _ in CATEGORY_RULES} | {"shopping": "Shopping"}
    return known.get(text.strip().lower(), text.strip())


def categorize(row: dict, user_rules=None) -> str:
    text = " ".join((row["counterparty"], row["purpose"], row["booking_text"]))
    for rx, cat in user_rules or []:
        if rx.search(text):
            return cat
    if _WALLET_RX.search(row["counterparty"]):
        text = f"{merchant_name(row)} {row['purpose']}"
    for cat, rx in _COMPILED:
        if rx.search(text):
            return cat
    for cat, rx in _BANK_COMPILED:
        if rx.search(row.get("bank_category") or ""):
            return cat
    return "Uncategorized"


def is_internal(row: dict, own_ibans: set[str], keywords: list[str], matched_ids: set[str]) -> bool:
    if row["id"] in matched_ids:
        return True
    if row["counterparty_iban"] and row["counterparty_iban"] in own_ibans:
        return True
    if (row.get("counterparty_bic") or "")[:8] in BROKER_BICS:
        return True
    if _BANK_INVESTMENT_RX.search(row.get("bank_category") or ""):
        return True
    hay = f"{row['counterparty']} {row['purpose']}".upper()
    return any(k and k.upper() in hay for k in keywords)


def classify(rows: list[dict], *, own_ibans=None, keywords=None, matched_ids=None, user_rules=None,
             offset_rules=None) -> list[dict]:
    """offset_rules: credits matching one of these count as a refund in that category,
    for example a parents' contribution that pays the semester fee."""
    own_ibans = set(own_ibans or ())
    keywords = DEFAULT_TRANSFER_KEYWORDS if keywords is None else keywords
    matched_ids = set(matched_ids or ())
    out = []
    for r in rows:
        r = dict(r)
        r["month"] = r["date"].strftime("%Y-%m")
        r["year"] = r["date"].year
        r["merchant"] = merchant_name(r)
        r["category"] = None
        if is_internal(r, own_ibans, keywords, matched_ids):
            r["kind"] = "internal"
        elif r["amount"] > 0:
            text = f"{r['booking_text']} {r['purpose']} {r['counterparty']}"
            offset = next((cat for rx, cat in offset_rules or [] if rx.search(text)), None)
            if offset:
                r["kind"], r["category"], r["offset"] = "expense", offset, True
            elif SALARY_RX.search(text):
                r["kind"], r["income_kind"] = "income", "Salary"
            elif REFUND_RX.search(text) or _WALLET_RX.search(r["counterparty"]):
                r["kind"], r["category"] = "expense", categorize(r, user_rules)
            elif INTEREST_RX.search(r["booking_text"]):
                r["kind"], r["income_kind"] = "income", "Interest"
            else:
                r["kind"], r["income_kind"] = "income", "Transfers in"
        else:
            r["kind"], r["category"] = "expense", categorize(r, user_rules)
        if r["kind"] == "expense":
            r["group"] = spending_group(r["category"])
        out.append(r)
    return out


# ---------------------------------------------------------------- recurring payments

_CADENCES = [("monthly", 25, 36, 30.44), ("quarterly", 80, 100, 91.3), ("half-yearly", 170, 200, 182.6), ("yearly", 350, 380, 365.25)]


def recurring_payments(rows: list[dict], today: date, kinds: tuple[str, ...] = ("expense",)) -> list[dict]:
    """Fixed costs: at least three similar debits to the same payee at a regular interval.
    kinds=("expense", "internal") also finds savings plans to your own depot."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["kind"] in kinds and r["amount"] < 0 and not r["pending"] and r["category"] != "Cash":
            # Wallets like PayPal use one mandate for every shop, so group those by shop.
            wallet = _WALLET_RX.search(r["counterparty"])
            key = f"{r['creditor_id']}|{r['mandate']}" if r["creditor_id"] and not wallet else r["merchant"]
            groups[key].append(r)
    out = []
    for grp in groups.values():
        grp.sort(key=lambda r: r["date"])
        grp = [r for r in grp if (today - r["date"]).days <= 800]
        if len(grp) < 3:
            continue
        gaps = [(b["date"] - a["date"]).days for a, b in zip(grp, grp[1:], strict=False) if (b["date"] - a["date"]).days > 3]
        if len(gaps) < 2:
            continue
        gap = median(gaps)
        cadence = next((c for c in _CADENCES if c[1] <= gap <= c[2]), None)
        if not cadence:
            continue
        amounts = [-r["amount"] for r in grp[-6:]]
        mean = sum(amounts) / len(amounts)
        if mean <= 0 or pstdev(amounts) / mean > 0.25:
            continue
        last = grp[-1]
        if (today - last["date"]).days > cadence[3] * 1.6:
            continue  # ended
        out.append(dict(
            name=last["merchant"], category=last["category"], cadence=cadence[0], amount=round(-last["amount"], 2),
            average=round(mean, 2), monthly=round(mean * 30.44 / cadence[3], 2), count=len(grp),
            last_date=last["date"].isoformat(), next_date=(last["date"] + timedelta(days=round(cadence[3]))).isoformat(),
            days=cadence[3],
        ))
    out.sort(key=lambda x: -x["monthly"])
    return out


# ---------------------------------------------------------------- cash flow forecast

FORECAST_DAYS = 30


def _next_month_day(d: date, day: int) -> date:
    y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    for dd in (day, 30, 29, 28):
        try:
            return date(y, m, dd)
        except ValueError:
            continue
    raise ValueError("invalid date")


def forecast_cash(rows: list[dict], recurring: list[dict], balance: float | None, today: date,
                  days: int = FORECAST_DAYS) -> dict | None:
    """Balance for the next days from fixed costs, salary, scheduled bookings, and average other spending."""
    if balance is None:
        return None
    end = today + timedelta(days=days)
    items: list[dict] = []
    for r in recurring:
        d, step = date.fromisoformat(r["next_date"]), timedelta(days=round(r["days"]))
        if d <= today:
            if (today - d).days > 7:
                d += step       # a late payment within a week is still expected, older ones are skipped
            else:
                d = today + timedelta(days=1)
        while d <= end:
            items.append({"date": d, "name": r["name"], "amount": -r["amount"], "kind": "fixed"})
            d += step
    booked = [r for r in rows if not r["pending"] and r["date"] <= today]
    salaries = [r for r in booked if r.get("income_kind") == "Salary"]
    next_salary = None
    if salaries and (today - salaries[-1]["date"]).days <= 45:
        last = salaries[-1]
        amount = round(sum(r["amount"] for r in salaries[-3:]) / len(salaries[-3:]), 2)
        d = _next_month_day(last["date"], last["date"].day)
        while d <= today:
            d = _next_month_day(d, last["date"].day)
        next_salary = {"date": d.isoformat(), "amount": amount, "from": last["merchant"]}
        while d <= end:
            items.append({"date": d, "name": last["merchant"], "amount": amount, "kind": "salary"})
            d = _next_month_day(d, last["date"].day)
    for r in rows:
        if r["pending"] or r["date"] > today:
            items.append({"date": max(r["date"], today + timedelta(days=1)), "name": r["merchant"], "amount": r["amount"],
                          "kind": "scheduled"})
    fixed_names = {r["name"] for r in recurring}
    window = [r for r in booked if (today - r["date"]).days < 90]
    span = min(90, max(1, (today - booked[0]["date"]).days)) if booked else 90
    variable = -sum(r["amount"] for r in window if r["kind"] == "expense" and r["merchant"] not in fixed_names) / span
    variable = max(variable, 0.0)

    by_day: dict[date, float] = defaultdict(float)
    for i in items:
        by_day[i["date"]] += i["amount"]
    series, value = [{"date": today.isoformat(), "balance": round(balance, 2)}], balance
    low, low_date = balance, today
    for n in range(1, days + 1):
        d = today + timedelta(days=n)
        value += by_day.get(d, 0.0) - variable
        series.append({"date": d.isoformat(), "balance": round(value, 2)})
        if value < low:
            low, low_date = value, d
    items.sort(key=lambda i: i["date"])
    return dict(
        start=round(balance, 2), end=round(value, 2), low=round(low, 2), low_date=low_date.isoformat(),
        daily_variable=round(variable, 2), next_salary=next_salary, days=days, series=series,
        items=[{**i, "date": i["date"].isoformat(), "amount": round(i["amount"], 2)} for i in items],
    )


# ---------------------------------------------------------------- transfers between accounts

def match_transfers(bank_rows: list[dict], broker_flows: list[dict], days: int = 4) -> tuple[set[str], set[str]]:
    """Pair bank debits with broker deposits (and broker withdrawals with bank credits)
    of the same amount within a few days. broker_flows: [{id, date, amount}] with
    amount > 0 for money arriving at the broker."""
    bank_ids, broker_ids = set(), set()
    free = sorted((r for r in bank_rows if not r["pending"]), key=lambda r: r["date"])
    used: set[str] = set()
    for f in sorted(broker_flows, key=lambda f: f["date"]):
        want = -round(f["amount"], 2)
        best = None
        for r in free:
            if r["id"] in used or round(r["amount"], 2) != want:
                continue
            delta = abs((r["date"] - f["date"]).days)
            if delta <= days and (best is None or delta < best[0]):
                best = (delta, r)
        if best:
            used.add(best[1]["id"])
            bank_ids.add(best[1]["id"])
            broker_ids.add(f["id"])
    return bank_ids, broker_ids


# ---------------------------------------------------------------- analysis

def _months_back(today: date, n: int) -> list[str]:
    y, m, out = today.year, today.month, []
    for _ in range(n):
        out.append(f"{y}-{m:02d}")
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return out[::-1]


def _top(items, key, limit):
    agg: dict[str, list] = {}
    for x in items:
        a = agg.setdefault(x[key], [0.0, 0])
        a[0] += -x["amount"]
        a[1] += 1
    return sorted(([k, round(v, 2), n] for k, (v, n) in agg.items() if round(v, 2) != 0), key=lambda r: -r[1])[:limit]


def analyze_bank(rows: list[dict], today: date, *, balances: dict[str, float] | None = None,
                 balance_anchors: dict[str, tuple[date, float]] | None = None) -> dict:
    """rows must come from classify(). balances: live balance per IBAN (FinTS);
    balance_anchors: (date, balance) per IBAN from balance.csv. Live wins."""
    # Future-dated rows (scheduled bookings) count as pending until their day.
    booked = [r for r in rows if not r["pending"] and r["date"] <= today]
    months24 = _months_back(today, 24)
    months12 = set(months24[-12:])
    this_m, prev_m = months24[-1], months24[-2]

    def spend(rs):
        return round(-sum(r["amount"] for r in rs if r["kind"] == "expense"), 2)

    def income(rs):
        return round(sum(r["amount"] for r in rs if r["kind"] == "income"), 2)

    def internal_out(rs):
        """Net money moved to own accounts and depots (out minus back)."""
        return round(-sum(r["amount"] for r in rs if r["kind"] == "internal"), 2)

    by_month = defaultdict(list)
    for r in booked:
        by_month[r["month"]].append(r)

    # Balance per account: live, or anchor plus bookings after the anchor date.
    accounts = sorted({r["account"] for r in rows if r["account"]} | set(balances or {}) | set(balance_anchors or {}))
    anchors: dict[str, tuple[date, float, str]] = {}
    for acc in accounts:
        if balances and balances.get(acc) is not None:
            anchors[acc] = (today, balances[acc], "live")
        elif balance_anchors and acc in balance_anchors:
            d, v = balance_anchors[acc]
            anchors[acc] = (d, v, f"anchor {d.isoformat()}")
    balance_now, history = None, []
    if anchors:
        def balance_at(end: date) -> float:
            total = 0.0
            for acc, (ad, av, _) in anchors.items():
                own = [r for r in booked if r["account"] == acc] if len(accounts) > 1 else booked
                total += av + sum(r["amount"] for r in own if ad < r["date"] <= end) - \
                    sum(r["amount"] for r in own if end < r["date"] <= ad)
            return round(total, 2)
        balance_now = balance_at(today)
        for m in months24:
            y, mo = int(m[:4]), int(m[5:])
            end = min(date(y + (mo == 12), mo % 12 + 1, 1) - timedelta(days=1), today)
            history.append({"month": m, "balance": balance_at(end)})
    sources = sorted({a[2] for a in anchors.values()})
    balance_source = ", ".join(sources) if sources else "none"
    missing_balance = [a for a in accounts if a not in anchors]

    monthly = []
    for m in months24:
        rs = by_month.get(m, [])
        groups = dict.fromkeys(GROUP_ORDER, 0.0)
        for r in rs:
            if r["kind"] == "expense":
                groups[r["group"]] -= r["amount"]
        inc, sp = income(rs), spend(rs)
        monthly.append({"month": m, "income": inc, "spending": sp, "saved": round(inc - sp, 2),
                        "to_depot": internal_out(rs), **{k: round(v, 2) for k, v in groups.items()}})

    # A calendar month is unusable for income: a salary at month end leaves it at zero for
    # most of the month. A rolling window always holds one of everything that repeats monthly.
    since_30d = today - timedelta(days=30)
    last30 = [r for r in booked if r["date"] > since_30d]
    prev30 = [r for r in booked if since_30d - timedelta(days=30) < r["date"] <= since_30d]

    last12 = [r for r in booked if r["month"] in months12]
    inc12, sp12 = income(last12), spend(last12)
    # Short histories: average over the months the export covers, not a fixed 12.
    months_12m = round(min(12.0, max(1.0, (today - booked[0]["date"]).days / 30.44)), 2) if booked else 12.0
    groups12 = dict.fromkeys(GROUP_ORDER, 0.0)
    for r in last12:
        if r["kind"] == "expense":
            groups12[r["group"]] -= r["amount"]
    salaries = [r for r in booked if r.get("income_kind") == "Salary"]
    recurring = recurring_payments(rows, today)
    years = []
    for y in sorted({r["year"] for r in booked}):
        ys = [r for r in booked if r["year"] == y]
        n = len({r["month"] for r in ys}) or 1
        years.append({"year": y, "income": income(ys), "spending": spend(ys), "saved": round(income(ys) - spend(ys), 2),
                      "months": n, "avg_spending": round(spend(ys) / n, 2)})
    income_kinds = defaultdict(float)
    for r in last12:
        if r["kind"] == "income":
            income_kinds[r["income_kind"]] += r["amount"]

    return dict(
        accounts=accounts, missing_balance=missing_balance,
        first_date=booked[0]["date"].isoformat() if booked else None,
        last_date=booked[-1]["date"].isoformat() if booked else None,
        transactions=len(booked), pending=len(rows) - len(booked),
        pending_amount=round(sum(r["amount"] for r in rows if r["pending"] or r["date"] > today), 2),
        balance=balance_now, balance_source=balance_source, balance_history=history,
        income_month=income(by_month.get(this_m, [])), income_prev_month=income(by_month.get(prev_m, [])),
        income_30d=income(last30), income_prev_30d=income(prev30),
        spending_30d=spend(last30), spending_prev_30d=spend(prev30),
        spending_month=spend(by_month.get(this_m, [])), spending_prev_month=spend(by_month.get(prev_m, [])),
        income_12m=inc12, spending_12m=sp12, avg_income_12m=round(inc12 / months_12m, 2), avg_spending_12m=round(sp12 / months_12m, 2), months_12m=months_12m,
        saved_12m=round(inc12 - sp12, 2),
        # A ratio against income is unbounded when the account sees the spending but not the income,
        # so euros are the headline and this is the detail underneath.
        savings_rate_12m=round((inc12 - sp12) / inc12 * 100, 1) if inc12 > 0 else None,
        to_depot_12m=internal_out(last12),
        income_kinds_12m={k: round(v, 2) for k, v in sorted(income_kinds.items(), key=lambda kv: -kv[1])},
        last_salary=({"date": salaries[-1]["date"].isoformat(), "amount": round(salaries[-1]["amount"], 2),
                      "from": salaries[-1]["merchant"]} if salaries else None),
        fixed_costs_month=round(sum(x["monthly"] for x in recurring), 2), recurring=recurring,
        forecast=forecast_cash(rows, recurring_payments(rows, today, ("expense", "internal")), balance_now, today),
        monthly=monthly, groups_12m={k: round(v, 2) for k, v in groups12.items()},
        categories_12m=_top([r for r in last12 if r["kind"] == "expense"], "category", 25),
        merchants_12m=_top([r for r in last12 if r["kind"] == "expense" and not r.get("offset")], "merchant", 15),
        merchants_month=_top([r for r in by_month.get(this_m, []) if r["kind"] == "expense" and not r.get("offset")], "merchant", 10),
        by_year=years,
    )
