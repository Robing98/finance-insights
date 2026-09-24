#!/usr/bin/env python3
"""Fail when the pinned requirements are incomplete, inconsistent, or unavailable.

Resolves the pinned lists from const.py the way Home Assistant would and compares the result
with the list itself. Anything pip pulls in that is neither pinned nor shipped by Home Assistant
is an unpinned dependency, which is exactly what the pinning is meant to prevent.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.pins import CORE  # noqa: E402

CONST = ROOT / "custom_components" / "finance_insights" / "const.py"


def pinned(name: str) -> tuple[str, ...]:
    """Read one requirement list out of const.py without importing the integration.

    This job installs nothing on purpose, so importing the package would pull in Home
    Assistant and fail. Reading the literal keeps the check independent of the environment.
    """
    for node in ast.parse(CONST.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return tuple(ast.literal_eval(node.value))
    raise SystemExit(f"{name} not found in {CONST.name}")


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
    fints, pytr = pinned("FINTS_REQUIREMENTS"), pinned("PYTR_REQUIREMENTS")
    problems = check("FinTS", fints) + check("pytr", pytr)
    for problem in problems:
        print(problem)
    if problems:
        print("\nRun scripts/pins.py and put the new lists into const.py.")
        return 1
    print(f"{len(fints) + len(pytr)} pinned requirements, nothing unpinned.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
