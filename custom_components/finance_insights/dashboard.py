"""Build a dashboard with an overview and detail tabs per person, keeping tabs the user changed.

Home Assistant has no per-user permissions for entities. Tab and section visibility only
hide content in the frontend; every user can still read all sensors.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
from pathlib import Path

import yaml

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import slugify

from .const import CONF_MEMBERS, CONF_OWNER, CONF_SHARED, DOMAIN, TYPE_BANK, TYPE_OVERVIEW, TYPE_TRADE_REPUBLIC, TYPE_UTILITY
from .coordinator import account_type, entity_prefix

_LOGGER = logging.getLogger(__name__)
TEMPLATES = Path(__file__).parent / "dashboards" / "sections.yaml"
LANGUAGES = ["en", "de"]
PRELUDE_EN = "{%- macro dt(v) -%}{{ v if v else '–' }}{%- endmacro -%}\n{%- set tr = {} -%}\n"
PRELUDE_DE = (
    "{%- macro dt(v) -%}{%- if not v -%}–{%- elif v | length >= 10 -%}{{ v[8:10] ~ '.' ~ v[5:7] ~ '.' ~ v[:4] }}"
    "{%- elif v | length == 7 -%}{{ v[5:7] ~ '.' ~ v[:4] }}{%- else -%}{{ v }}{%- endif -%}{%- endmacro -%}\n"
    "{%- set tr = __VALUES__ -%}\n"
)
TOPICS = {"overview": "Overview", "portfolio": "Portfolio", "bonds": "Bonds", "dividends": "Dividends",
          "spending": "Spending", "costs": "Running costs", "income": "Income", "charts": "Charts", "data": "Data"}
# Entity prefixes used in the templates.
TEMPLATE_PREFIX = {TYPE_TRADE_REPUBLIC: "trade_republic", TYPE_BANK: "sparkasse", TYPE_OVERVIEW: "finance_overview",
                   TYPE_UTILITY: "electricity"}
UNASSIGNED = "Unassigned"


def load_templates() -> dict[str, dict[str, list[dict]]]:
    """Blocking: read the section templates shipped with the integration."""
    return yaml.safe_load(TEMPLATES.read_text(encoding="utf-8"))


def load_language(language: str) -> dict | None:
    """Blocking: the text catalog for a language, None for English."""
    if language == "en":
        return None
    return yaml.safe_load((TEMPLATES.parent / f"{language}.yaml").read_text(encoding="utf-8"))


def _localize(node, catalog: dict | None, key: str | None = None):
    """Translate headings, titles, and series names, and give Markdown cards dt() and tr."""
    if isinstance(node, dict):
        return {k: _localize(v, catalog, k) for k, v in node.items()}
    if isinstance(node, list):
        return [_localize(v, catalog, key) for v in node]
    if not isinstance(node, str):
        return node
    if key == "content":
        if catalog is None:
            return PRELUDE_EN + node
        for en, translated in catalog["phrases"]:
            node = node.replace(en, translated)
        return PRELUDE_DE.replace("__VALUES__", json.dumps(catalog["values"], ensure_ascii=False)) + node
    if key in ("heading", "title", "name", "label") and catalog:
        return catalog["strings"].get(node, node)
    return node


def _rewrite(node, kind: str, prefix: str, title: str):
    base = TEMPLATE_PREFIX[kind]
    if isinstance(node, dict):
        return {k: _rewrite(v, kind, prefix, title) for k, v in node.items()}
    if isinstance(node, list):
        return [_rewrite(v, kind, prefix, title) for v in node]
    if isinstance(node, str):
        if prefix != base:
            for domain in ("sensor", "button"):
                node = node.replace(f"{domain}.{base}_", f"{domain}.{prefix}_")
        if kind == TYPE_TRADE_REPUBLIC:
            node = node.replace("'attributes.trade_republic_holding', 'defined'",
                                f"'attributes.trade_republic_holding', 'eq', '{prefix}'")
            node = node.replace("replace('Trade Republic ', '')", f"replace('{title} ', '')")
    return node


def _set_heading(section: dict, text: str) -> None:
    for card in section.get("cards", []):
        if card.get("type") == "heading":
            card["heading"] = text
            return


def _slug(text: str) -> str:
    return slugify(text).replace("_", "-")


def _people(entry: ConfigEntry) -> list[str]:
    return list(dict.fromkeys(u for u in [entry.options.get(CONF_OWNER), *(entry.options.get(CONF_SHARED) or [])] if u))


def build_views(entries: list[ConfigEntry], templates: dict, users: dict[str, str], catalog: dict | None = None) -> list[dict]:
    """users: HA user id -> name. catalog: from load_language(). One group of tabs per owner, plus household tabs."""
    tabs = {**TOPICS, **(catalog or {}).get("tabs", {})}
    unassigned = tabs.get("unassigned", UNASSIGNED)
    accounts = [e for e in entries if account_type(e) != TYPE_OVERVIEW]
    overviews = [e for e in entries if account_type(e) == TYPE_OVERVIEW]
    owners = sorted({e.options.get(CONF_OWNER) for e in accounts}, key=lambda o: (o is None, users.get(o or "", "")))
    personal = {o: [ov for ov in overviews if (ov.options.get(CONF_MEMBERS) or []) == [o]] for o in owners if o}
    households = [ov for ov in overviews if ov not in [x for xs in personal.values() for x in xs]]
    several_groups = len(owners) > 1
    kind_order = {TYPE_TRADE_REPUBLIC: 0, TYPE_BANK: 1, TYPE_UTILITY: 2}
    views: list[dict] = []

    for owner in owners:
        accs = sorted((e for e in accounts if e.options.get(CONF_OWNER) == owner),
                      key=lambda e: (kind_order[account_type(e)], e.title.lower()))
        name = users.get(owner or "", unassigned) if owner else unassigned
        viewers = list(dict.fromkeys(u for e in accs for u in _people(e))) if owner else []
        per_kind = {k: sum(account_type(e) == k for e in accs) for k in kind_order}
        # Paths don't depend on the language, so changing it keeps the tabs.
        slug = _slug(users.get(owner or "", "")) or (owner or "unassigned")[:8] if owner else "unassigned"
        prefix_title = several_groups and (owner is None or len(viewers) > 1)
        for topic in TOPICS:
            label = tabs[topic]
            sections: list[dict] = []
            if topic == "overview":
                for ov in personal.get(owner, []):
                    sections += [_localize(_rewrite(copy.deepcopy(s), TYPE_OVERVIEW, entity_prefix(ov), ov.title), catalog)
                                 for s in templates[TYPE_OVERVIEW]["overview"]]
            for acc in accs:
                kind = account_type(acc)
                for tpl in templates[kind].get(topic, []):
                    section = _localize(_rewrite(copy.deepcopy(tpl), kind, entity_prefix(acc), acc.title), catalog)
                    heading = next((c["heading"] for c in section["cards"] if c.get("type") == "heading"), label)
                    if topic == "overview":
                        _set_heading(section, acc.title)
                    elif kind in (TYPE_BANK, TYPE_UTILITY) or per_kind[kind] > 1:
                        _set_heading(section, f"{acc.title}: {heading}")
                    # Accounts shared with fewer people than the tab: hide their sections from the others.
                    if owner and set(_people(acc)) != set(viewers):
                        section["visibility"] = [{"condition": "user", "users": _people(acc)}]
                    sections.append(section)
            if not sections:
                continue
            view = {"title": f"{name}: {label}" if prefix_title else label, "path": f"{slug}-{topic}",
                    "type": "sections", "max_columns": 3, "sections": sections}
            if viewers:
                view["visible"] = [{"user": u} for u in viewers]
            views.append(view)

    for ov in households:
        members = ov.options.get(CONF_MEMBERS) or []
        view = {"title": ov.title, "path": f"household-{_slug(ov.title) or ov.entry_id[:8]}", "type": "sections",
                "max_columns": 3, "sections": [_localize(_rewrite(copy.deepcopy(s), TYPE_OVERVIEW, entity_prefix(ov), ov.title),
                                                         catalog) for s in templates[TYPE_OVERVIEW]["overview"]]}
        if members:
            view["visible"] = [{"user": u} for u in members]
        views.append(view)
    return views


def view_hash(view: dict) -> str:
    return hashlib.sha1(json.dumps(view, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def merge_views(current: list[dict], generated: list[dict], hashes: dict[str, str], reset: bool = False):
    """Replace generated tabs the user hasn't changed, keep changed and own tabs, don't restore deleted ones.

    hashes: path -> hash of the tab as it was last written. Returns (views, hashes, stats).
    """
    gen = {v["path"]: v for v in generated}
    out: list[dict] = []
    new_hashes: dict[str, str] = {}
    stats = {"updated": 0, "added": 0, "removed": 0, "kept_changed": 0, "kept_deleted": 0}
    placed: set[str] = set()
    for view in current:
        path = view.get("path")
        if path not in hashes:
            out.append(view)  # the user's own tab
            continue
        untouched = hashes[path] == view_hash(view)
        if path in gen and (untouched or reset):
            out.append(gen[path])
            new_hashes[path] = view_hash(gen[path])
            stats["updated"] += 1
        elif path in gen:
            out.append(view)
            new_hashes[path] = hashes[path]
            stats["kept_changed"] += 1
        elif untouched:
            stats["removed"] += 1  # its account is gone
            continue
        else:
            out.append(view)  # changed, and no longer generated: now the user's tab
            continue
        placed.add(path)
    for i, view in enumerate(generated):
        path = view["path"]
        if path in placed:
            continue
        if path in hashes and not reset:
            new_hashes[path] = hashes[path]  # deleted by the user: stays deleted
            stats["kept_deleted"] += 1
            continue
        pos = len(out)
        for prev in reversed(generated[:i]):
            idx = next((j for j, v in enumerate(out) if v.get("path") == prev["path"]), None)
            if idx is not None:
                pos = idx + 1
                break
        else:
            later = [j for j, v in enumerate(out) if v.get("path") in gen]
            pos = later[0] if later else len(out)
        out.insert(pos, view)
        placed.add(path)
        new_hashes[path] = view_hash(view)
        stats["added"] += 1
    return out, new_hashes, stats


async def async_build_dashboard(hass: HomeAssistant, url_path: str, hashes: dict[str, str] | None,
                                reset: bool = False, language: str = "en") -> tuple[dict[str, str], dict]:
    """Update the storage dashboard at url_path. hashes None: every existing tab was generated before."""
    from homeassistant.components.lovelace.const import LOVELACE_DATA, ConfigNotFound
    from homeassistant.components.lovelace.dashboard import LovelaceStorage

    data = hass.data.get(LOVELACE_DATA)
    dashboard = data.dashboards.get(url_path) if data and url_path else None
    if not isinstance(dashboard, LovelaceStorage) or url_path == "lovelace":
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="dashboard_not_found", translation_placeholders={"dashboard": url_path})
    try:
        current = await dashboard.async_load(False)
    except ConfigNotFound:
        current = {}
    views = current.get("views") or []
    if hashes is None:
        hashes = {v["path"]: view_hash(v) for v in views if v.get("path")}
    templates = await hass.async_add_executor_job(load_templates)
    catalog = await hass.async_add_executor_job(load_language, language)
    users = {u.id: u.name for u in await hass.auth.async_get_users() if not u.system_generated}
    generated = build_views(hass.config_entries.async_entries(DOMAIN), templates, users, catalog)
    merged, new_hashes, stats = merge_views(views, generated, hashes, reset)
    title = current.get("title") or ("Finanzen" if language == "de" else "Finances")
    await dashboard.async_save({**current, "title": title, "views": merged})
    stats["views"] = len(merged)
    _LOGGER.debug("Dashboard %s: %s", url_path, stats)
    return new_hashes, stats
