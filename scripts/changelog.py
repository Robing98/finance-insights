"""Read one version's section out of CHANGELOG.md.

The release workflow uses this for the release notes, and the test suite uses it to make sure a
version bump without notes fails in CI rather than at release time.

Usage: python scripts/changelog.py 0.13.0
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = ROOT / "CHANGELOG.md"
HEADING = re.compile(r"^## +(\S+)\s*$", re.MULTILINE)


def versions(text: str) -> list[str]:
    """Every version the changelog documents, in the order it lists them."""
    return HEADING.findall(text)


def section(text: str, version: str) -> str | None:
    """The body under `## <version>`, without the heading. None when the version is missing."""
    for match in HEADING.finditer(text):
        if match.group(1) != version:
            continue
        end = HEADING.search(text, match.end())
        return text[match.end():end.start() if end else len(text)].strip("\n")
    return None


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    version = argv[1].lstrip("v")
    body = section(CHANGELOG.read_text(encoding="utf-8"), version)
    if body is None:
        print(f"CHANGELOG.md has no section '## {version}'. Add one before releasing.", file=sys.stderr)
        return 1
    print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
