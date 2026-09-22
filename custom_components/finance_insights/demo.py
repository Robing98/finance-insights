"""Demo accounts with sample data, so people can try the integration before connecting their own."""
from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path

DEMO_DIR = "finance_insights_demo"
DEMO_TR_TITLE = "Trade Republic Demo"
DEMO_BANK_TITLE = "Sparkasse Demo"
TR_FOLDER = f"{DEMO_DIR}/trade_republic"
BANK_FOLDER = f"{DEMO_DIR}/sparkasse"
_SOURCE = Path(__file__).parent / "demo"
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})")
_DE = re.compile(r'"(\d{2})\.(\d{2})\.(\d{2})"')


def _shift(year: int, month: int, day: int, months: int) -> date:
    total = year * 12 + month - 1 + months
    y, m = divmod(total, 12)
    for d in (day, 30, 29, 28):
        try:
            return date(y, m + 1, d)
        except ValueError:
            continue
    raise ValueError("invalid date")


def _months_until(last: date, today: date) -> int:
    return (today.year - last.year) * 12 + today.month - last.month


def _shift_tr(text: str, today: date) -> str:
    lines = text.splitlines(keepends=True)
    head, rows = lines[0], lines[1:]
    last = max(date.fromisoformat(r.split(",")[1].strip('"')) for r in rows if r.strip())
    months = _months_until(last, today)
    out = []
    for r in rows:
        first, second, rest = r.split(",", 2)
        new = _shift(*(int(x) for x in _ISO.search(second).groups()), months)
        if new > today:
            continue  # bookings after today would look like the future
        stamp = _ISO.sub(new.isoformat(), first, count=1)
        out.append(f"{stamp},\"{new.isoformat()}\",{rest}")
    return head + "".join(out)


def _shift_bank(text: str, today: date) -> str:
    lines = text.splitlines(keepends=True)
    head, rows = lines[0], lines[1:]

    def parse(m):
        return int("20" + m.group(3)), int(m.group(2)), int(m.group(1))

    last = max(date(*parse(_DE.search(r))) for r in rows if r.strip())
    months = _months_until(last, today)
    out = []
    for r in rows:
        first = _DE.search(r)
        if first and _shift(*parse(first), months) > today:
            continue  # bookings after today would look like the future
        out.append(_DE.sub(lambda m: f'"{_shift(*parse(m), months):%d.%m.%y}"', r))
    return head + "".join(out)


def write_demo_files(config_dir: str, today: date) -> None:
    """Copy the sample exports into the config folder with dates moved up to the current month."""
    base = Path(config_dir)
    for src, folder, name, shift in (("trade_republic.csv", TR_FOLDER, "demo.csv", _shift_tr),
                                     ("sparkasse.csv", BANK_FOLDER, "demo.csv", _shift_bank)):
        raw = (_SOURCE / src).read_bytes()
        encoding = "utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "utf-8"
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            encoding = "cp1252"
            text = raw.decode(encoding)
        target = base / folder
        target.mkdir(parents=True, exist_ok=True)
        data, path = shift(text, today).encode(encoding), target / name
        if path.exists() and path.read_bytes() == data:
            continue
        # Atomic: the other demo account may be reading its file at the same time during startup.
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)
