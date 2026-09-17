"""Build one dashboard with a view per account and overview, each visible to its people.

Home Assistant has no per-user permissions for entities. View visibility only hides
views in the frontend; every user can still read all sensors.
"""
from __future__ import annotations

import copy
import logging
from pathlib import Path

import yaml

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from .const import CONF_MEMBERS, CONF_OWNER, CONF_SHARED, DOMAIN, TYPE_BANK, TYPE_OVERVIEW, TYPE_TRADE_REPUBLIC
from .coordinator import account_type, entity_prefix

_LOGGER = logging.getLogger(__name__)
TEMPLATES = Path(__file__).parent / "dashboards"


def load_templates() -> dict[str, list[dict]]:
    """Blocking: read the dashboard templates shipped with the integration."""
    depot = yaml.safe_load((TEMPLATES / "depot.yaml").read_text(encoding="utf-8"))
    finance = yaml.safe_load((TEMPLATES / "finance.yaml").read_text(encoding="utf-8"))
    by_path = {v["path"]: v for v in finance["views"]}
    return {TYPE_TRADE_REPUBLIC: depot["views"], TYPE_BANK: [by_path["sparkasse"]], TYPE_OVERVIEW: [by_path["overview"]]}


# Entity prefixes used in the templates.
TEMPLATE_PREFIX = {TYPE_TRADE_REPUBLIC: "trade_republic", TYPE_BANK: "sparkasse", TYPE_OVERVIEW: "finance_overview"}


def _rewrite(node, kind: str, prefix: str, title: str):
    base = TEMPLATE_PREFIX[kind]
    if isinstance(node, dict):
        return {k: _rewrite(v, kind, prefix, title) for k, v in node.items()}
    if isinstance(node, list):
        return [_rewrite(v, kind, prefix, title) for v in node]
    if isinstance(node, str) and prefix != base:
        for domain in ("sensor", "button"):
            node = node.replace(f"{domain}.{base}_", f"{domain}.{prefix}_")
    if isinstance(node, str) and kind == TYPE_TRADE_REPUBLIC:
        node = node.replace("'attributes.trade_republic_holding', 'defined'",
                            f"'attributes.trade_republic_holding', 'eq', '{prefix}'")
        node = node.replace("replace('Trade Republic ', '')", f"replace('{title} ', '')")
    return node


def _visible(user_ids: list[str]) -> list[dict] | None:
    ids = list(dict.fromkeys(u for u in user_ids if u))
    return [{"user": u} for u in ids] if ids else None


def build_views(entries: list[ConfigEntry], templates: dict[str, list[dict]]) -> list[dict]:
    order = {TYPE_OVERVIEW: 0, TYPE_TRADE_REPUBLIC: 1, TYPE_BANK: 2}
    entries = sorted(entries, key=lambda e: (order[account_type(e)], e.title.lower()))
    counts = {k: sum(account_type(e) == k for e in entries) for k in order}
    views = []
    for entry in entries:
        kind, prefix = account_type(entry), entity_prefix(entry)
        if kind == TYPE_OVERVIEW:
            people = entry.options.get(CONF_MEMBERS) or []
        else:
            people = [entry.options.get(CONF_OWNER), *(entry.options.get(CONF_SHARED) or [])]
        for tpl in templates[kind]:
            view = _rewrite(copy.deepcopy(tpl), kind, prefix, entry.title)
            label = entry.title
            if kind == TYPE_TRADE_REPUBLIC and counts[kind] == 1 and entry.title == "Trade Republic":
                label = ""
            view["title"] = f"{label}: {tpl['title']}" if label and len(templates[kind]) > 1 else (label or tpl["title"])
            view["path"] = f"{prefix.replace('_', '-')}-{tpl['path']}"
            if visible := _visible(people):
                view["visible"] = visible
            else:
                view.pop("visible", None)
            views.append(view)
    return views


async def async_build_dashboard(hass: HomeAssistant, url_path: str) -> int:
    """Overwrite the storage dashboard at url_path. Returns the number of views."""
    from homeassistant.components.lovelace.const import LOVELACE_DATA
    from homeassistant.components.lovelace.dashboard import LovelaceStorage

    data = hass.data.get(LOVELACE_DATA)
    dashboard = data.dashboards.get(url_path) if data else None
    if not isinstance(dashboard, LovelaceStorage) or url_path in (None, "lovelace"):
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="dashboard_not_found", translation_placeholders={"dashboard": url_path})
    templates = await hass.async_add_executor_job(load_templates)
    views = build_views(hass.config_entries.async_entries(DOMAIN), templates)
    await dashboard.async_save({"title": "Finances", "views": views})
    _LOGGER.debug("Wrote %d views to dashboard %s", len(views), url_path)
    return len(views)
