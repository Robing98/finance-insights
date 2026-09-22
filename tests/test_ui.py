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
    with patch("homeassistant.components.frontend.add_extra_js_url") as add:
        await async_register_frontend(hass)  # "frontend" not in components yet
        assert add.call_count == 0
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
        await hass.async_block_till_done()
    assert add.call_args.args[1].startswith(f"{FRONTEND_URL}/finance-insights-cards.js?v=")


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
