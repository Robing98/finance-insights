"""The changelog is what users read in HACS when they update, so it has to stay complete."""
import json
from pathlib import Path

from scripts.changelog import section, versions

ROOT = Path(__file__).parent.parent
TEXT = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
MANIFEST = json.loads((ROOT / "custom_components" / "finance_insights" / "manifest.json").read_text(encoding="utf-8"))


def _key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def test_the_version_being_shipped_has_release_notes():
    """A version bump without notes must fail here, not when the tag is already pushed."""
    body = section(TEXT, MANIFEST["version"])
    assert body, f"CHANGELOG.md has no section for {MANIFEST['version']}"
    assert len(body.split()) > 20, "the section is too short to tell anyone what changed"


def test_the_newest_release_comes_first():
    listed = versions(TEXT)
    assert listed[0] == MANIFEST["version"]
    assert listed == sorted(listed, key=_key, reverse=True)


def test_every_heading_is_a_version_number():
    assert all(part.isdigit() for v in versions(TEXT) for part in v.split("."))
    assert len(set(versions(TEXT))) == len(versions(TEXT))  # no version twice


def test_a_section_stops_at_the_next_version():
    body = section(TEXT, "0.11.0")
    assert "Business account" in body and "savings rate" not in body


def test_an_unknown_version_has_no_section():
    assert section(TEXT, "9.9.9") is None


def test_the_release_workflow_uses_the_changelog():
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "scripts/changelog.py" in workflow and "cat section.md" in workflow
