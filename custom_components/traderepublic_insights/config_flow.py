"""Config flow: CSV folder, optional pytr login (push confirmation or authenticator code)."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    SOURCE_REAUTH, ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.requirements import RequirementsNotFound, async_process_requirements

from . import pytr_client
from .const import (
    CONF_CODE, CONF_FOLDER, CONF_PHONE, CONF_PIN, CONF_SCAN_MINUTES, CONF_TIMELINE_HOURS,
    CONF_USE_PYTR, DEFAULT_FOLDER, DEFAULT_SCAN_MINUTES, DEFAULT_TIMELINE_HOURS, DOMAIN,
    PYTR_REQUIREMENT,
)
from .coordinator import cookies_path

_LOGGER = logging.getLogger(__name__)

PHONE_SCHEMA = vol.Schema({
    vol.Required(CONF_PHONE): selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.TEL)),
    vol.Required(CONF_PIN): selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)),
})


class TRConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._api = None
        self._needs_code = False

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            folder = user_input[CONF_FOLDER].strip()
            path = Path(self.hass.config.path(folder))
            try:
                await self.hass.async_add_executor_job(lambda: path.mkdir(parents=True, exist_ok=True))
            except OSError:
                errors[CONF_FOLDER] = "folder_invalid"
            else:
                await self.async_set_unique_id(str(path))
                self._abort_if_unique_id_configured()
                self._data = {CONF_FOLDER: folder, CONF_USE_PYTR: user_input[CONF_USE_PYTR]}
                if user_input[CONF_USE_PYTR]:
                    return await self.async_step_pytr()
                return self.async_create_entry(title="Trade Republic", data=self._data)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_FOLDER, default=DEFAULT_FOLDER): str,
                vol.Required(CONF_USE_PYTR, default=False): bool,
            }),
            errors=errors,
            description_placeholders={"config_dir": self.hass.config.config_dir},
        )

    async def _start_login(self, phone: str, pin: str) -> str | None:
        try:
            await async_process_requirements(self.hass, DOMAIN, [PYTR_REQUIREMENT])
        except RequirementsNotFound:
            return "pytr_install_failed"
        try:
            self._api, self._needs_code = await self.hass.async_add_executor_job(
                pytr_client.start_login, phone, pin, cookies_path(self.hass, phone))
        except Exception:  # noqa: BLE001 - pytr raises ValueError, HTTPError, and others
            _LOGGER.exception("Trade Republic login could not be started")
            return "login_failed"
        self._data.update({CONF_PHONE: phone, CONF_PIN: pin})
        return None

    async def async_step_pytr(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            phone = user_input[CONF_PHONE].replace(" ", "")
            if not phone.startswith("+"):
                errors[CONF_PHONE] = "phone_format"
            elif err := await self._start_login(phone, user_input[CONF_PIN]):
                errors["base"] = err
            else:
                return await self.async_step_pytr_confirm()
        return self.async_show_form(step_id="pytr", data_schema=PHONE_SCHEMA, errors=errors)

    async def async_step_pytr_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await self.hass.async_add_executor_job(
                    pytr_client.finish_login, self._api, user_input.get(CONF_CODE))
            except pytr_client.PytrNotConfirmed:
                errors["base"] = "not_confirmed"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Trade Republic login could not be completed")
                errors["base"] = "login_failed"
            else:
                if self.source == SOURCE_REAUTH:
                    return self.async_update_reload_and_abort(self._get_reauth_entry(), data_updates=self._data)
                return self.async_create_entry(title="Trade Republic", data=self._data)

        schema = vol.Schema({vol.Required(CONF_CODE): str}) if self._needs_code else vol.Schema({})
        return self.async_show_form(
            step_id="pytr_confirm_code" if self._needs_code else "pytr_confirm",
            data_schema=schema, errors=errors,
        )

    async_step_pytr_confirm_code = async_step_pytr_confirm

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        self._data = dict(entry_data)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if err := await self._start_login(self._data[CONF_PHONE], user_input[CONF_PIN]):
                errors["base"] = err
            else:
                return await self.async_step_pytr_confirm()
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PIN): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD))}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return TROptionsFlow()


class TROptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        opts = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(CONF_SCAN_MINUTES, default=opts.get(CONF_SCAN_MINUTES, DEFAULT_SCAN_MINUTES)):
                    vol.All(vol.Coerce(int), vol.Range(min=5, max=1440)),
                vol.Required(CONF_TIMELINE_HOURS, default=opts.get(CONF_TIMELINE_HOURS, DEFAULT_TIMELINE_HOURS)):
                    vol.All(vol.Coerce(int), vol.Range(min=1, max=168)),
            }),
        )
