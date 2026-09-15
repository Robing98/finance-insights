"""Config flow: add a Trade Republic account, a bank account, or the overview."""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    SOURCE_REAUTH, ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.requirements import RequirementsNotFound, async_process_requirements

from . import fints_client, pytr_client
from .const import (
    CONF_ACCOUNT_TYPE, CONF_BLZ, CONF_OFFSET_RULES, CONF_CODE, CONF_FINTS_HOURS, CONF_FOLDER, CONF_IBAN, CONF_LOGIN, CONF_NAME,
    CONF_PHONE, CONF_PIN, CONF_PRODUCT_ID, CONF_SCAN_MINUTES, CONF_SERVER, CONF_TAN, CONF_TIMELINE_HOURS,
    CONF_TRANSFER_KEYWORDS, CONF_USE_FINTS, CONF_USE_PYTR, DEFAULT_BANK_FOLDER, DEFAULT_BANK_NAME,
    DEFAULT_FINTS_HOURS, DEFAULT_SCAN_MINUTES, DEFAULT_TIMELINE_HOURS, DEFAULT_TR_FOLDER, DOMAIN, FINTS_REQUIREMENT,
    LEGACY_DOMAIN, PYTR_REQUIREMENT, TYPE_BANK, TYPE_OVERVIEW, TYPE_TRADE_REPUBLIC,
)
from .coordinator import cookies_path, fints_state_path, legacy_cookies_path

_LOGGER = logging.getLogger(__name__)

PASSWORD = selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD))
TEL = selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.TEL))
MULTILINE = selector.TextSelector(selector.TextSelectorConfig(multiline=True))
URL = selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.URL))


class FIConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._api = None
        self._needs_code = False
        self._fints = None
        self._ibans: list[str] = []

    # ------------------------------------------------------------ start

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        options = ["trade_republic", "bank"]
        if not any(e.data.get(CONF_ACCOUNT_TYPE) == TYPE_OVERVIEW for e in self._async_current_entries()):
            options.append("overview")
        if self.hass.config_entries.async_entries(LEGACY_DOMAIN):
            options.insert(0, "import_legacy")
        return self.async_show_menu(step_id="user", menu_options=options)

    async def _folder(self, folder: str) -> tuple[Path | None, str | None]:
        path = Path(self.hass.config.path(folder.strip()))
        try:
            await self.hass.async_add_executor_job(lambda: path.mkdir(parents=True, exist_ok=True))
        except OSError:
            return None, "folder_invalid"
        return path, None

    # ------------------------------------------------------------ import from Trade Republic Insights

    async def async_step_import_legacy(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        legacy = self.hass.config_entries.async_entries(LEGACY_DOMAIN)
        if not legacy:
            return self.async_abort(reason="no_legacy")
        old = legacy[0]
        if user_input is not None:
            data = {CONF_ACCOUNT_TYPE: TYPE_TRADE_REPUBLIC, CONF_FOLDER: old.data.get(CONF_FOLDER, DEFAULT_TR_FOLDER),
                    CONF_USE_PYTR: old.data.get(CONF_USE_PYTR, False)}
            if data[CONF_USE_PYTR]:
                data.update({CONF_PHONE: old.data[CONF_PHONE], CONF_PIN: old.data[CONF_PIN]})
                src, dst = legacy_cookies_path(self.hass, data[CONF_PHONE]), cookies_path(self.hass, data[CONF_PHONE])
                await self.hass.async_add_executor_job(lambda: src.exists() and not dst.exists() and shutil.copy2(src, dst))
            path = Path(self.hass.config.path(data[CONF_FOLDER]))
            await self.async_set_unique_id(f"{TYPE_TRADE_REPUBLIC}:{path}")
            self._abort_if_unique_id_configured()
            # Remove the old entry first so the entity IDs (sensor.trade_republic_*) are free again.
            await self.hass.config_entries.async_remove(old.entry_id)
            return self.async_create_entry(title="Trade Republic", data=data, options=dict(old.options))
        return self.async_show_form(step_id="import_legacy", data_schema=vol.Schema({}),
                                    description_placeholders={"folder": old.data.get(CONF_FOLDER, "")})

    # ------------------------------------------------------------ Trade Republic

    async def async_step_trade_republic(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            path, err = await self._folder(user_input[CONF_FOLDER])
            if err:
                errors[CONF_FOLDER] = err
            else:
                await self.async_set_unique_id(f"{TYPE_TRADE_REPUBLIC}:{path}")
                self._abort_if_unique_id_configured()
                self._data = {CONF_ACCOUNT_TYPE: TYPE_TRADE_REPUBLIC, CONF_FOLDER: user_input[CONF_FOLDER].strip(),
                              CONF_USE_PYTR: user_input[CONF_USE_PYTR]}
                if user_input[CONF_USE_PYTR]:
                    return await self.async_step_pytr()
                return self.async_create_entry(title="Trade Republic", data=self._data)
        return self.async_show_form(
            step_id="trade_republic",
            data_schema=vol.Schema({vol.Required(CONF_FOLDER, default=DEFAULT_TR_FOLDER): str,
                                    vol.Required(CONF_USE_PYTR, default=False): bool}),
            errors=errors, description_placeholders={"config_dir": self.hass.config.config_dir},
        )

    async def _start_pytr(self, phone: str, pin: str) -> str | None:
        try:
            await async_process_requirements(self.hass, DOMAIN, [PYTR_REQUIREMENT])
        except RequirementsNotFound:
            return "install_failed"
        try:
            self._api, self._needs_code = await self.hass.async_add_executor_job(
                pytr_client.start_login, phone, pin, cookies_path(self.hass, phone))
        except Exception:  # noqa: BLE001 - pytr raises many types
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
            elif err := await self._start_pytr(phone, user_input[CONF_PIN]):
                errors["base"] = err
            else:
                return await self.async_step_pytr_confirm()
        return self.async_show_form(step_id="pytr", data_schema=vol.Schema({
            vol.Required(CONF_PHONE): TEL, vol.Required(CONF_PIN): PASSWORD}), errors=errors)

    async def async_step_pytr_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await self.hass.async_add_executor_job(pytr_client.finish_login, self._api, user_input.get(CONF_CODE))
            except pytr_client.PytrNotConfirmed:
                errors["base"] = "not_confirmed"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Trade Republic login could not be completed")
                errors["base"] = "login_failed"
            else:
                return self._finish("Trade Republic")
        schema = vol.Schema({vol.Required(CONF_CODE): str}) if self._needs_code else vol.Schema({})
        return self.async_show_form(step_id="pytr_confirm_code" if self._needs_code else "pytr_confirm",
                                    data_schema=schema, errors=errors)

    async_step_pytr_confirm_code = async_step_pytr_confirm

    # ------------------------------------------------------------ Bank

    async def async_step_bank(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            path, err = await self._folder(user_input[CONF_FOLDER])
            if err:
                errors[CONF_FOLDER] = err
            else:
                await self.async_set_unique_id(f"{TYPE_BANK}:{path}")
                self._abort_if_unique_id_configured()
                self._data = {CONF_ACCOUNT_TYPE: TYPE_BANK, CONF_NAME: user_input[CONF_NAME].strip(),
                              CONF_FOLDER: user_input[CONF_FOLDER].strip(), CONF_USE_FINTS: user_input[CONF_USE_FINTS]}
                if user_input[CONF_USE_FINTS]:
                    return await self.async_step_fints()
                return self.async_create_entry(title=self._data[CONF_NAME], data=self._data)
        return self.async_show_form(
            step_id="bank",
            data_schema=vol.Schema({vol.Required(CONF_NAME, default=DEFAULT_BANK_NAME): str,
                                    vol.Required(CONF_FOLDER, default=DEFAULT_BANK_FOLDER): str,
                                    vol.Required(CONF_USE_FINTS, default=False): bool}),
            errors=errors, description_placeholders={"config_dir": self.hass.config.config_dir},
        )

    async def _start_fints(self, data: dict[str, Any]) -> str | None:
        try:
            await async_process_requirements(self.hass, DOMAIN, [FINTS_REQUIREMENT])
        except RequirementsNotFound:
            return "install_failed"
        try:
            self._fints = await self.hass.async_add_executor_job(
                fints_client.start_login, data[CONF_BLZ], data[CONF_LOGIN], data[CONF_PIN], data[CONF_SERVER],
                data[CONF_PRODUCT_ID], fints_state_path(self.hass, data[CONF_BLZ], data[CONF_LOGIN]))
        except Exception:  # noqa: BLE001 - python-fints raises many types
            _LOGGER.exception("FinTS login could not be started")
            return "login_failed"
        return None

    def _fints_schema(self, defaults: dict[str, Any]) -> vol.Schema:
        return vol.Schema({
            vol.Required(CONF_BLZ, default=defaults.get(CONF_BLZ, "")): str,
            vol.Required(CONF_SERVER, default=defaults.get(CONF_SERVER, "")): URL,
            vol.Required(CONF_LOGIN, default=defaults.get(CONF_LOGIN, "")): str,
            vol.Required(CONF_PIN): PASSWORD,
            vol.Required(CONF_PRODUCT_ID, default=defaults.get(CONF_PRODUCT_ID, "")): PASSWORD,
        })

    async def async_step_fints(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            values = {k: v.strip() for k, v in user_input.items()}
            if not values[CONF_BLZ].isdigit() or len(values[CONF_BLZ]) != 8:
                errors[CONF_BLZ] = "blz_format"
            elif not values[CONF_SERVER].startswith("https://"):
                errors[CONF_SERVER] = "server_format"
            elif err := await self._start_fints(values):
                errors["base"] = err
            else:
                self._data.update(values)
                return await self.async_step_fints_tan()
        return self.async_show_form(step_id="fints", data_schema=self._fints_schema(self._data), errors=errors)

    async def async_step_fints_tan(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                self._ibans = await self.hass.async_add_executor_job(
                    fints_client.finish_login, self._fints, user_input.get(CONF_TAN))
            except fints_client.FinTSNotConfirmed:
                errors["base"] = "not_confirmed"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("FinTS login could not be completed")
                errors["base"] = "login_failed"
            else:
                return await self.async_step_fints_account()
        decoupled = self._fints.decoupled
        return self.async_show_form(
            step_id="fints_tan" if decoupled else "fints_tan_code",
            data_schema=vol.Schema({}) if decoupled else vol.Schema({vol.Required(CONF_TAN): str}),
            errors=errors, description_placeholders={"challenge": self._fints.challenge_text or "-"},
        )

    async_step_fints_tan_code = async_step_fints_tan

    async def async_step_fints_account(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if len(self._ibans) == 1 and user_input is None:
            user_input = {CONF_IBAN: self._ibans[0]}
        if user_input is not None:
            self._data[CONF_IBAN] = user_input[CONF_IBAN].replace(" ", "")
            return self._finish(self._data.get(CONF_NAME, DEFAULT_BANK_NAME))
        return self.async_show_form(step_id="fints_account", data_schema=vol.Schema({
            vol.Required(CONF_IBAN): selector.SelectSelector(selector.SelectSelectorConfig(options=self._ibans))}))

    # ------------------------------------------------------------ Overview

    async def async_step_overview(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(TYPE_OVERVIEW)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            return self.async_create_entry(title="Finance overview", data={CONF_ACCOUNT_TYPE: TYPE_OVERVIEW})
        return self.async_show_form(step_id="overview", data_schema=vol.Schema({}))

    # ------------------------------------------------------------ reauth

    def _finish(self, title: str) -> ConfigFlowResult:
        if self.source == SOURCE_REAUTH:
            return self.async_update_reload_and_abort(self._get_reauth_entry(), data_updates=self._data)
        return self.async_create_entry(title=title, data=self._data)

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        self._data = dict(entry_data)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        is_bank = self._data.get(CONF_ACCOUNT_TYPE) == TYPE_BANK
        if user_input is not None:
            if is_bank:
                values = {**self._data, CONF_PIN: user_input[CONF_PIN]}
                if err := await self._start_fints(values):
                    errors["base"] = err
                else:
                    self._data = values
                    self._ibans = [self._data[CONF_IBAN]]
                    return await self.async_step_fints_tan()
            elif err := await self._start_pytr(self._data[CONF_PHONE], user_input[CONF_PIN]):
                errors["base"] = err
            else:
                return await self.async_step_pytr_confirm()
        return self.async_show_form(step_id="reauth_confirm", data_schema=vol.Schema({vol.Required(CONF_PIN): PASSWORD}),
                                    errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return FIOptionsFlow()


class FIOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        opts = self.config_entry.options
        kind = self.config_entry.data.get(CONF_ACCOUNT_TYPE, TYPE_TRADE_REPUBLIC)
        fields: dict = {}
        if kind != TYPE_OVERVIEW:
            fields[vol.Required(CONF_SCAN_MINUTES, default=opts.get(CONF_SCAN_MINUTES, DEFAULT_SCAN_MINUTES))] = \
                vol.All(vol.Coerce(int), vol.Range(min=5, max=1440))
        if kind == TYPE_TRADE_REPUBLIC:
            fields[vol.Required(CONF_TIMELINE_HOURS, default=opts.get(CONF_TIMELINE_HOURS, DEFAULT_TIMELINE_HOURS))] = \
                vol.All(vol.Coerce(int), vol.Range(min=1, max=168))
        if kind == TYPE_BANK:
            fields[vol.Required(CONF_FINTS_HOURS, default=opts.get(CONF_FINTS_HOURS, DEFAULT_FINTS_HOURS))] = \
                vol.All(vol.Coerce(int), vol.Range(min=1, max=168))
            fields[vol.Optional(CONF_TRANSFER_KEYWORDS, default=opts.get(CONF_TRANSFER_KEYWORDS, "Trade Republic"))] = str
            fields[vol.Optional(CONF_OFFSET_RULES, default=opts.get(CONF_OFFSET_RULES, ""))] = MULTILINE
        if not fields:
            return self.async_abort(reason="no_options")
        return self.async_show_form(step_id="init", data_schema=vol.Schema(fields))
