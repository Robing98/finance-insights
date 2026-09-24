"""Read Finance Insights cards the way finance-insights-cards.js does, so tests can check them against real sensors.

Covers what the cards take from the sensors: rows and raw cell values, not their formatting.
"""
from __future__ import annotations

PREFIX = "custom:finance-insights-"


def get(obj, key):
    if obj is None or key is None:
        return None
    if isinstance(key, int):
        return obj[key] if isinstance(obj, (list, tuple)) and key < len(obj) else None
    for part in str(key).split("."):
        obj = obj.get(part) if isinstance(obj, dict) else None
    return obj


def cards(view, kind=None):
    found = [c for s in view["sections"] for c in s["cards"]]
    return [c for c in found if kind is None or c["type"] == PREFIX + kind]


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def table_rows(hass, card) -> list[dict]:
    if card.get("holdings"):
        rows = [{**s.attributes, "state": _num(s.state), "name": str(s.attributes.get("friendly_name", s.entity_id)).replace(card.get("strip_name", ""), "")}
                for s in hass.states.async_all("sensor") if s.attributes.get("trade_republic_holding") == card["holdings"]]
    else:
        state = hass.states.get(card["entity"])
        value = state.attributes.get(card.get("attribute")) if state else None
        rows = list(value) if isinstance(value, list) else [{"key": k, "value": v} for k, v in value.items()] if isinstance(value, dict) else []
    if "sort" in card:
        rows.sort(key=lambda r: -(_num(get(r, card["sort"])) if _num(get(r, card["sort"])) is not None else float("-inf")))
    if card.get("reverse"):
        rows.reverse()
    return rows[: card["limit"]] if card.get("limit") else rows


def cell(card, row, col):
    if "only_if" in col and not get(row, col["only_if"]):
        return None
    v = get(row, col["key"])
    if "divide_by" in col:
        d = _num(get(row, col["divide_by"]))
        v = _num(v) / d if d else None
    if col.get("divide") and _num(v) is not None:
        v = _num(v) / col["divide"]
    if "map" in col:
        v = col["map"].get(str(v), col.get("map_default", v))
    if col.get("translate") and card.get("values"):
        v = card["values"].get(v, v)
    return v


def table(hass, card) -> list[list]:
    """Rows of a table card as lists of raw cell values."""
    return [[cell(card, r, c) for c in card["columns"]] for r in table_rows(hass, card)]


def check_sources(hass, view) -> list[str]:
    """Problems where a card points at an attribute or row key the sensors don't have."""
    problems = []
    for card in cards(view):
        kind = card["type"].removeprefix(PREFIX)
        state = hass.states.get(card.get("entity", "")) if card.get("entity") else None
        if kind in ("table", "bars", "donut") and not card.get("holdings"):
            if state is None or state.state in ("unknown", "unavailable"):
                continue
            if card.get("attribute") not in state.attributes and not (kind == "bars" and "attribute" not in card):
                problems.append(f"{card['entity']} has no attribute {card.get('attribute')}")
                continue
        if kind == "table":
            rows = table_rows(hass, card)
            for col in card["columns"] if rows else []:
                keys = [col["key"], col.get("divide_by"), col.get("only_if"), col.get("estimated_key"), col.get("warn_key")]
                for key in (k for k in keys if k is not None):
                    if all(get(r, key) is None and not (isinstance(r, dict) and str(key).split(".")[0] in r) for r in rows):
                        problems.append(f"{card.get('entity') or card.get('holdings')}.{card.get('attribute', '')}: no {key}")
        if kind == "facts" and state is not None and not (card.get("requires") and state.attributes.get(card["requires"]) is None):
            for row in card["rows"]:
                if "attribute" in row and not row.get("optional") and str(row["attribute"]).split(".")[0] not in state.attributes:
                    problems.append(f"{card['entity']} has no attribute {row['attribute']}")
        if kind == "sankey" and state is not None and state.state not in ("unknown", "unavailable"):
            for key in (card.get("sources_attribute", "sources"), card.get("uses_attribute", "uses")):
                if key not in state.attributes:
                    problems.append(f"{card['entity']} has no attribute {key}")
        if kind == "bars" and state is not None and state.state not in ("unknown", "unavailable"):
            rows = state.attributes.get(card.get("attribute", "monthly")) or []
            for series in card["series"]:
                # get(), like the card itself, resolves a nested key such as "in.Salary".
                if rows and all(get(r, series["key"]) is None for r in rows):
                    problems.append(f"{card['entity']}.{card.get('attribute', 'monthly')}: no {series['key']}")
    return problems
