#!/usr/bin/env python3
"""Fail when something that looks like a credential is about to be published.

The FinTS product ID belongs to one registration. The Deutsche Kreditwirtschaft can block a
number it finds in use by third parties, and that would lock out every legitimate user of the
product it belongs to. So no real product ID, IBAN, or PIN may reach this repository.

Known fixtures are listed in ALLOWED. Add to it only for values that are invented.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_SUFFIXES = {".woff2", ".png", ".jpg", ".svg", ".ico", ".zip"}
# Invented values used by the tests and the demo data.
ALLOWED = {
    "DE12500500000123456789", "DE00100123450000000001", "DE00300000000000000002",
    "ABCDEFGHIJKLMNOPQRSTUVWXY", "A" * 25,
}
PATTERNS = {
    # 25 characters with at least one digit: the shape of a FinTS product ID.
    "FinTS product ID": re.compile(r"(?<![0-9A-Z])(?=[0-9A-Z]{25}(?![0-9A-Z]))(?=[0-9A-Z]*[0-9])[0-9A-Z]{25}"),
    "German IBAN": re.compile(r"\bDE\d{20}\b"),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}


def is_real_iban(value: str) -> bool:
    """A real IBAN passes the mod-97 check. Invented ones in fixtures normally do not."""
    rearranged = value[4:] + value[:4]
    digits = "".join(str(int(c, 36)) for c in rearranged)
    return int(digits) % 97 == 1


def tracked() -> list[Path]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True)
    return [ROOT / name for name in out.stdout.split("\n") if name]


def main() -> int:
    findings = []
    for path in tracked():
        if path.suffix in SKIP_SUFFIXES or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for line_number, line in enumerate(text.splitlines(), 1):
            for label, pattern in PATTERNS.items():
                for match in pattern.findall(line):
                    if label == "German IBAN" and not is_real_iban(match):
                        continue  # an invented account number, not one that exists
                    if match not in ALLOWED:
                        findings.append(f"{path.relative_to(ROOT)}:{line_number}: {label} ({match[:4]}…)")
    for finding in findings:
        print(finding)
    if findings:
        print("\nRemove it, or add the invented value to ALLOWED in scripts/check_secrets.py.")
        return 1
    print(f"{len(tracked())} tracked files, nothing that looks like a credential.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
