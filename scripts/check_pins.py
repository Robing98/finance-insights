#!/usr/bin/env python3
"""Fail when the pinned requirements are incomplete, inconsistent, or unavailable.

Resolves the pinned lists from const.py the way Home Assistant would and compares the result
with the list itself. Anything pip pulls in that is neither pinned nor shipped by Home Assistant
is an unpinned dependency, which is exactly what the pinning is meant to prevent.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from custom_components.finance_insights.const import FINTS_REQUIREMENTS, PYTR_REQUIREMENTS  # noqa: E402
from scripts.pins import CORE  # noqa: E402


def resolved(specs: tuple[str, ...]) -> dict[str, str]:
    with tempfile.NamedTemporaryFile(suffix=".json") as report:
        subprocess.run([sys.executable, "-m", "pip", "install", "--dry-run", "--ignore-installed",
                        "--quiet", "--report", report.name, *specs], check=True)
        data = json.load(open(report.name, encoding="utf-8"))
    return {i["metadata"]["name"].lower().replace("_", "-"): i["metadata"]["version"] for i in data["install"]}


def check(name: str, specs: tuple[str, ...]) -> list[str]:
    problems = []
    pinned = {}
    for spec in specs:
        if "==" not in spec:
            problems.append(f"{name}: {spec} is not pinned to an exact version")
            continue
        package, version = spec.split("==")
        pinned[package.lower().replace("_", "-")] = version
    for package, version in resolved(specs).items():
        if package in CORE:
            continue
        if package not in pinned:
            problems.append(f"{name}: {package}=={version} is installed but not pinned")
        elif pinned[package] != version:
            problems.append(f"{name}: {package} is pinned to {pinned[package]} but resolves to {version}")
    return problems


def main() -> int:
    problems = check("FinTS", FINTS_REQUIREMENTS) + check("pytr", PYTR_REQUIREMENTS)
    for problem in problems:
        print(problem)
    if problems:
        print("\nRun scripts/pins.py and put the new lists into const.py.")
        return 1
    print(f"{len(FINTS_REQUIREMENTS) + len(PYTR_REQUIREMENTS)} pinned requirements, nothing unpinned.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
