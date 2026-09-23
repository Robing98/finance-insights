#!/usr/bin/env python3
"""Regenerate the pinned requirement lists in const.py.

Usage: python scripts/pins.py [pytr==0.4.10] [fints==5.0.0]

Resolves each package and prints the exact versions of everything pip would install, minus the
packages Home Assistant already ships. Home Assistant installs each requirement on its own with
its own constraints, so pinning a package it ships would fight those constraints.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile

# Shipped by Home Assistant itself or by its own dependencies.
CORE = {"requests", "urllib3", "idna", "charset-normalizer", "certifi", "typing-extensions",
        "packaging", "cryptography", "cffi", "pycparser", "pygments", "babel", "attrs", "yarl",
        "aiohttp", "jinja2", "pyyaml", "voluptuous"}


def resolve(spec: str) -> dict[str, str]:
    with tempfile.NamedTemporaryFile(suffix=".json") as report:
        subprocess.run([sys.executable, "-m", "pip", "install", "--dry-run", "--ignore-installed",
                        "--quiet", "--report", report.name, spec], check=True)
        data = json.load(open(report.name, encoding="utf-8"))
    found = {}
    for item in data["install"]:
        meta = item["metadata"]
        name = meta["name"].lower().replace("_", "-")
        if name not in CORE:
            found[name] = meta["version"]
    return found


def main(specs: list[str]) -> int:
    for spec in specs:
        top = re.split(r"[<>=!~]", spec)[0].lower()
        versions = resolve(spec)
        versions.pop(top, None)
        lines = [f'    "{name}=={version}",' for name, version in sorted(versions.items())]
        lines.append(f'    "{spec}",')
        print(f"{top.upper()}_REQUIREMENTS = (")
        print("\n".join(lines))
        print(")\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or ["pytr==0.4.10", "fints==5.0.0"]))
