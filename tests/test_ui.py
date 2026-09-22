"""The cards served by the integration and the optional theme."""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import yaml
from homeassistant.helpers import issue_registry as ir

from custom_components.finance_insights.const import DOMAIN, FRONTEND_URL, THEME_NAME
from custom_components.finance_insights.ui import FRONTEND_DIR, async_install_theme, async_register_frontend

FONTS = ["ibm-plex-sans-latin-400-normal.woff2", "ibm-plex-sans-latin-500-normal.woff2",
         "ibm-plex-sans-latin-600-normal.woff2", "space-grotesk-latin-500-normal.woff2", "space-grotesk-latin-600-normal.woff2"]


def test_frontend_files_are_shipped():
    script = (FRONTEND_DIR / "finance-insights-cards.js").read_text(encoding="utf-8")
    for font in FONTS:
        assert (FRONTEND_DIR / "fonts" / font).exists() and font in script
    for tag in ("hero", "kpis", "bars", "forecast", "accounts"):
        assert f'"finance-insights-{tag}"' in script
    # Every card used in the templates is defined by the script.
    templates = (Path(FRONTEND_DIR).parent / "dashboards" / "sections.yaml").read_text(encoding="utf-8")
    for used in {line.split("custom:")[1].strip() for line in templates.splitlines() if "custom:finance-insights-" in line}:
        assert f'"{used}"' in script, used


async def test_register_frontend(hass):
    hass.config.components.add("frontend")
    hass.http = MagicMock(async_register_static_paths=AsyncMock())
    with patch("homeassistant.components.frontend.add_extra_js_url") as add:
        await async_register_frontend(hass)
    config = hass.http.async_register_static_paths.call_args.args[0][0]
    assert config.url_path == FRONTEND_URL and Path(config.path) == FRONTEND_DIR
    url = add.call_args.args[1]
    assert url.startswith(f"{FRONTEND_URL}/finance-insights-cards.js?v=")


async def test_register_frontend_when_frontend_loads_later(hass):
    """Frontend replaces its URL list while it sets up, so the cards are announced again after start."""
    from homeassistant.const import EVENT_HOMEASSISTANT_STARTED

    hass.http = MagicMock(async_register_static_paths=AsyncMock())
    with patch("homeassistant.components.frontend.add_extra_js_url", side_effect=[KeyError, None]) as add:
        await async_register_frontend(hass)  # frontend is not set up yet, so the first call fails
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
        await hass.async_block_till_done()
    assert add.call_count == 2
    assert add.call_args.args[1].startswith(f"{FRONTEND_URL}/finance-insights-cards.js?v=")


async def test_register_frontend_uses_lovelace_resources(hass):
    """A dashboard waits for its resources, so the cards must be registered as one."""
    from homeassistant.components.lovelace.const import LOVELACE_DATA

    items: list[dict] = []

    async def create(data):
        items.append({"id": "1", "type": data["res_type"], "url": data["url"]})
        return items[-1]

    async def update(item_id, updates):
        items[0].update(updates)
        return items[0]

    resources = MagicMock(async_get_info=AsyncMock(), async_items=lambda: items,
                          async_create_item=AsyncMock(side_effect=create), async_update_item=AsyncMock(side_effect=update))
    hass.data[LOVELACE_DATA] = MagicMock(resource_mode="storage", resources=resources)
    hass.http = MagicMock(async_register_static_paths=AsyncMock())

    with patch("homeassistant.components.frontend.add_extra_js_url") as add:
        await async_register_frontend(hass)
        assert add.call_count == 0
    assert len(items) == 1 and items[0]["type"] == "module"
    assert items[0]["url"].startswith(f"{FRONTEND_URL}/finance-insights-cards.js?v=")

    items[0]["url"] = f"{FRONTEND_URL}/finance-insights-cards.js?v=0.0.1"
    with patch("homeassistant.components.frontend.add_extra_js_url") as add:
        await async_register_frontend(hass)  # an update leaves one resource, pointing at the new version
        assert add.call_count == 0
    assert len(items) == 1 and not items[0]["url"].endswith("0.0.1")


async def test_register_frontend_with_yaml_resources(hass):
    """Resources cannot be written in YAML mode, so the cards are loaded as a module URL instead."""
    from homeassistant.components.lovelace.const import LOVELACE_DATA

    hass.data[LOVELACE_DATA] = MagicMock(resource_mode="yaml")
    hass.http = MagicMock(async_register_static_paths=AsyncMock())
    with patch("homeassistant.components.frontend.add_extra_js_url") as add:
        await async_register_frontend(hass)
    assert add.call_count == 1


async def test_register_frontend_without_http(hass):
    hass.http = None
    await async_register_frontend(hass)  # no error in setups without a web server


async def test_install_theme(hass, tmp_path):
    hass.config.config_dir = str(tmp_path)
    hass.data["frontend_themes"] = {}

    async def reload(call):
        # Like Home Assistant with `themes: !include_dir_merge_named themes` in configuration.yaml.
        themes = {}
        for file in (tmp_path / "themes").glob("*.yaml"):
            themes.update(yaml.safe_load(file.read_text(encoding="utf-8")))
        hass.data["frontend_themes"] = themes

    hass.services.async_register("frontend", "reload_themes", reload)
    assert await async_install_theme(hass)
    theme = hass.data["frontend_themes"][THEME_NAME]
    assert set(theme["modes"]) == {"dark", "light"} and theme["modes"]["dark"]["fi-mint"] == "#5fd4a4"
    assert ir.async_get(hass).async_get_issue(DOMAIN, "theme_not_loaded") is None


async def test_theme_not_loaded_creates_issue(hass, tmp_path):
    hass.config.config_dir = str(tmp_path)
    assert not await async_install_theme(hass)
    assert (tmp_path / "themes" / "finance_insights.yaml").exists()
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "theme_not_loaded")
    assert issue is not None and issue.translation_placeholders == {"file": "themes/finance_insights.yaml"}
