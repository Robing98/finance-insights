"""Frontend for the generated dashboard: the Finance Insights cards and the optional theme."""
from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.loader import async_get_integration

from .const import DOMAIN, FRONTEND_URL, THEME_FILE, THEME_NAME

_LOGGER = logging.getLogger(__name__)
FRONTEND_DIR = Path(__file__).parent / "frontend"
THEME_SOURCE = Path(__file__).parent / "themes" / THEME_FILE
ISSUE_THEME = "theme_not_loaded"


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Serve the cards and load them on every dashboard, so users don't install a separate frontend plugin."""
    if hass.http is None or "frontend" not in hass.config.components:
        return
    from homeassistant.components.frontend import add_extra_js_url
    from homeassistant.components.http import StaticPathConfig

    integration = await async_get_integration(hass, DOMAIN)
    await hass.http.async_register_static_paths([StaticPathConfig(FRONTEND_URL, str(FRONTEND_DIR), True)])
    # The version in the URL makes browsers load new cards after an update despite the cache headers.
    add_extra_js_url(hass, f"{FRONTEND_URL}/finance-insights-cards.js?v={integration.version}")


def _copy_theme(target: Path) -> bool:
    """Blocking: write the theme file when it is missing or outdated. Returns whether it changed."""
    text = THEME_SOURCE.read_text(encoding="utf-8")
    if target.exists() and target.read_text(encoding="utf-8") == text:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return True


async def async_install_theme(hass: HomeAssistant) -> bool:
    """Put the theme into /config/themes and reload themes. Returns whether Home Assistant knows the theme.

    Home Assistant loads that folder only with `frontend: themes: !include_dir_merge_named themes` in
    configuration.yaml, which new installations have. Without it, a repair issue explains the line.
    """
    target = Path(hass.config.path("themes", THEME_FILE))
    changed = await hass.async_add_executor_job(_copy_theme, target)
    themes = hass.data.get("frontend_themes")
    if (changed or (themes is not None and THEME_NAME not in themes)) and hass.services.has_service("frontend", "reload_themes"):
        try:
            await hass.services.async_call("frontend", "reload_themes", blocking=True)
        except HomeAssistantError as err:
            _LOGGER.warning("Could not reload themes: %s", err)
    loaded = THEME_NAME in (hass.data.get("frontend_themes") or {})
    if loaded:
        ir.async_delete_issue(hass, DOMAIN, ISSUE_THEME)
    else:
        ir.async_create_issue(hass, DOMAIN, ISSUE_THEME, is_fixable=False, severity=ir.IssueSeverity.WARNING,
                              translation_key=ISSUE_THEME, translation_placeholders={"file": f"themes/{THEME_FILE}"},
                              learn_more_url="https://github.com/Robing98/finance-insights#theme")
    return loaded
