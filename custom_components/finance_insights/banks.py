"""Bank search for the FinTS setup.

Bank codes and names come from the Deutsche Bundesbank's bank code file (bundled).
The FinTS server URLs are not bundled: the FinTS bank list must not be shipped with
software. Registered FinTS manufacturers can put their own copy of the list into the
config folder as fints_banks.csv, and the search then fills in the URL as well.
"""
from __future__ import annotations

import csv
import io
import json
import re
from functools import lru_cache
from pathlib import Path

OWN_LIST = "fints_banks.csv"
MAX_RESULTS = 25


@lru_cache(maxsize=1)
def _banks() -> list[tuple[str, str, str]]:
    data = json.loads((Path(__file__).parent / "banks_de.json").read_text(encoding="utf-8"))
    return [tuple(b) for b in data["banks"]]


def bank_code_from(text: str) -> str | None:
    """Bank code from a German IBAN or an 8-digit bank code."""
    compact = re.sub(r"\s", "", text).upper()
    if re.fullmatch(r"DE\d{20}", compact):
        return compact[4:12]
    if re.fullmatch(r"\d{8}", compact):
        return compact
    return None


def search(query: str) -> list[dict]:
    """Banks matching a name (every word must occur), a bank code, or an IBAN."""
    code = bank_code_from(query)
    if code:
        hits = [b for b in _banks() if b[0] == code]
    else:
        words = [w for w in re.split(r"\s+", query.casefold().strip()) if w]
        if not words:
            return []
        hits = [b for b in _banks() if all(w in b[1].casefold() for w in words)]
        phrase = " ".join(words)

        def rank(b):
            name = b[1].casefold()
            whole = all(re.search(rf"\b{re.escape(w)}\b", name) for w in words)
            return (name != phrase, not name.startswith(phrase), not whole, name)

        hits.sort(key=rank)
    return [{"blz": b[0], "name": b[1], "bic": b[2]} for b in hits[:MAX_RESULTS]]


def name_of(blz: str) -> str | None:
    return next((b[1] for b in _banks() if b[0] == blz), None)


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def own_urls(paths: list[Path]) -> dict[str, str]:
    """Bank code -> PIN/TAN URL from the user's own FinTS bank list, if one is present."""
    for path in paths:
        if not path.is_file():
            continue
        text = _decode(path.read_bytes())
        delimiter = ";" if text[:4096].count(";") >= text[:4096].count(",") else ","
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        fields = reader.fieldnames or []
        blz_col = next((f for f in fields if f and f.strip().upper() == "BLZ"), None)
        url_col = next((f for f in fields if f and "PIN/TAN" in f.upper() and "URL" in f.upper()), None)
        if not blz_col or not url_col:
            continue
        out = {}
        for row in reader:
            blz, url = (row.get(blz_col) or "").strip(), (row.get(url_col) or "").strip()
            if re.fullmatch(r"\d{8}", blz) and url.startswith("https://") and blz not in out:
                out[blz] = url
        return out
    return {}
