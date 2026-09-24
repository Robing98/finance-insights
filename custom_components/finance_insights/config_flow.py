"""Config flow: add a Trade Republic account, a bank account, or the overview."""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    SOURCE_REAUTH, ConfigEntry, ConfigFlow, ConfigFlowResult, ConfigSubentryFlow, OptionsFlow, SubentryFlowResult, SOURCE_IMPORT,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
from homeassistant.requirements import RequirementsNotFound, async_process_requirements
from homeassistant.util import dt as dt_util

from . import banks, demo, fints_client, pytr_client, vault
from .const import (
    CONF_ACCOUNT_TYPE, CONF_BANK_SEARCH, CONF_DEMO, CONF_BENCHMARKS, CONF_BLZ, CONF_DIVIDEND_API_KEY, CONF_DIVIDEND_PROVIDER, CONF_MARKET_HOURS, DEFAULT_MARKET_ONLINE,
    CONF_WATCHLIST, CONF_YAHOO_FALLBACK, DEFAULT_MARKET_HOURS, DIVIDEND_PROVIDERS, CONF_MEMBERS, CONF_OFFSET_RULES, CONF_OWNER, CONF_SHARED, DEFAULT_OVERVIEW_TITLE,
    DEFAULT_TR_TITLE, CONF_CODE, CONF_FINTS_HOURS, CONF_FOLDER, CONF_IBAN, CONF_LOGIN, CONF_NAME,
    CONF_ASK_PIN, CONF_PHONE, CONF_PIN, CONF_PIN_CONFIRM, CONF_PRODUCT_ID, CONF_SCAN_MINUTES, CONF_SERVER, CONF_TAN, CONF_TIMELINE_HOURS,
    CONF_TAX_ALLOWANCE, CONF_TAX_CHURCH, CONF_TAX_JOINT, CONF_TAX_OTHER_INCOME, CONF_TRANSFER_KEYWORDS, CONF_USE_FINTS, CONF_USE_PYTR, DEFAULT_BANK_FOLDER, DEFAULT_BANK_NAME,
    DEFAULT_FINTS_HOURS, DEFAULT_SCAN_MINUTES, DEFAULT_TIMELINE_HOURS, TAX_CHURCH_RATES, DEFAULT_TR_FOLDER, DOMAIN, FINTS_REQUIREMENTS,
    LEGACY_DOMAIN, PYTR_REQUIREMENTS, TYPE_BANK, TYPE_OVERVIEW, TYPE_TRADE_REPUBLIC,
)
from .const import (
    CONF_ADVANCE, CONF_BASE_PRICE, CONF_BONUS, CONF_END, CONF_KWH_PER_M3, CONF_NOTICE_WEEKS, CONF_START, CONF_STATISTIC,
    CONF_SUPPLIER, CONF_UNIT_PRICE, CONF_UTILITY, SUBENTRY_CONTRACT, TYPE_UTILITY,
)
from .coordinator import cookies_path, energy_defaults, fints_state_path, legacy_cookies_path
from .utility_core import BILLING_UNIT, UTILITY_TYPES

_LOGGER = logging.getLogger(__name__)

PASSWORD = selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD))
TEL = selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.TEL))
MULTILINE = selector.TextSelector(selector.TextSelectorConfig(multiline=True))
URL = selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.URL))


async def _user_options(hass: HomeAssistant) -> list[selector.SelectOptionDict]:
    users = await hass.auth.async_get_users()
    return [selector.SelectOptionDict(value=u.id, label=u.name or u.id)
            for u in users if u.is_active and not u.system_generated]


def _people_schema(options: list, owner: str | None, shared: list[str]) -> dict:
    return {
        vol.Optional(CONF_OWNER, description={"suggested_value": owner}):
            selector.SelectSelector(selector.SelectSelectorConfig(options=options)),
        vol.Optional(CONF_SHARED, default=shared):
            selector.SelectSelector(selector.SelectSelectorConfig(options=options, multiple=True)),
    }


class FIConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._api = None
        self._needs_code = False
        self._fints = None
        self._ibans: list[str] = []
        self._bank_reason = ""
        self._bank_hits: list[dict] = []
        self._bank_label = ""
        self._title = DEFAULT_TR_TITLE

    # ------------------------------------------------------------ start

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        options = ["trade_republic", "bank", "utility", "overview", "demo"]
        if self.hass.config_entries.async_entries(LEGACY_DOMAIN):
            options.insert(0, "import_legacy")
        return self.async_show_menu(step_id="user", menu_options=options)

    async def _folder(self, folder: str) -> tuple[Path | None, str | None]:
        if not folder.strip() or ".." in Path(folder.strip()).parts:
            return None, "folder_invalid"
        path = Path(self.hass.config.path(folder.strip()))
        try:
            await self.hass.async_add_executor_job(lambda: path.mkdir(parents=True, exist_ok=True))
        except OSError:
            return None, "folder_invalid"
        return path, None

    # ------------------------------------------------------------ demo

    async def async_step_demo(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """A Trade Republic and a Sparkasse account with sample data, to try the dashboard first."""
        path = Path(self.hass.config.path(demo.TR_FOLDER))
        # raise_on_progress=False: every unique ID here comes from what the user typed, so a flow
        # left behind by a closed browser or a dropped connection must not block a new one.
        await self.async_set_unique_id(f"{TYPE_TRADE_REPUBLIC}:{path}", raise_on_progress=False)
        self._abort_if_unique_id_configured()
        if user_input is None:
            return self.async_show_form(step_id="demo", data_schema=vol.Schema({}),
                                        description_placeholders={"folder": demo.DEMO_DIR})
        await self.hass.async_add_executor_job(demo.write_demo_files, self.hass.config.config_dir, dt_util.now().date())
        options = self._owner_options()
        bank = {CONF_ACCOUNT_TYPE: TYPE_BANK, CONF_NAME: demo.DEMO_BANK_TITLE, CONF_FOLDER: demo.BANK_FOLDER,
                CONF_USE_FINTS: False, CONF_DEMO: True}
        self.hass.async_create_task(self.hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_IMPORT}, data={"data": bank, "options": options, "title": demo.DEMO_BANK_TITLE}))
        return self.async_create_entry(title=demo.DEMO_TR_TITLE, options=options, data={
            CONF_ACCOUNT_TYPE: TYPE_TRADE_REPUBLIC, CONF_FOLDER: demo.TR_FOLDER, CONF_USE_PYTR: False, CONF_DEMO: True})

    async def async_step_import(self, import_data: dict[str, Any]) -> ConfigFlowResult:
        """Second account of the demo."""
        data = import_data["data"]
        path = Path(self.hass.config.path(data[CONF_FOLDER]))
        await self.async_set_unique_id(f"{data[CONF_ACCOUNT_TYPE]}:{path}", raise_on_progress=False)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=import_data["title"], data=data, options=import_data["options"])

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
            await self.async_set_unique_id(f"{TYPE_TRADE_REPUBLIC}:{path}", raise_on_progress=False)
            self._abort_if_unique_id_configured()
            # Remove the old entry first so the entity IDs (sensor.trade_republic_*) are free again.
            await self.hass.config_entries.async_remove(old.entry_id)
            return self.async_create_entry(title=DEFAULT_TR_TITLE, data=data, options={**self._owner_options(), **old.options})
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
                await self.async_set_unique_id(f"{TYPE_TRADE_REPUBLIC}:{path}", raise_on_progress=False)
                self._abort_if_unique_id_configured()
                self._title = user_input[CONF_NAME].strip() or DEFAULT_TR_TITLE
                self._data = {CONF_ACCOUNT_TYPE: TYPE_TRADE_REPUBLIC, CONF_FOLDER: user_input[CONF_FOLDER].strip(),
                              CONF_USE_PYTR: user_input[CONF_USE_PYTR]}
                if user_input[CONF_USE_PYTR]:
                    return await self.async_step_pytr()
                return self._finish(self._title)
        first = not any(e.data.get(CONF_ACCOUNT_TYPE) == TYPE_TRADE_REPUBLIC for e in self._async_current_entries())
        typed = user_input or {}
        return self.async_show_form(
            step_id="trade_republic",
            data_schema=vol.Schema({vol.Required(CONF_NAME, default=typed.get(CONF_NAME, DEFAULT_TR_TITLE if first else "")): str,
                                    vol.Required(CONF_FOLDER, default=typed.get(CONF_FOLDER, DEFAULT_TR_FOLDER if first else "")): str,
                                    vol.Required(CONF_USE_PYTR, default=typed.get(CONF_USE_PYTR, False)): bool}),
            errors=errors, description_placeholders={"config_dir": self.hass.config.config_dir},
        )

    async def _start_pytr(self, phone: str, pin: str) -> str | None:
        try:
            await async_process_requirements(self.hass, DOMAIN, list(PYTR_REQUIREMENTS))
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
            vol.Required(CONF_PHONE, default=(user_input or {}).get(CONF_PHONE, self._data.get(CONF_PHONE, ""))): TEL,
            vol.Required(CONF_PIN): PASSWORD}), errors=errors)

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
                return self._finish(self._title)
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
                await self.async_set_unique_id(f"{TYPE_BANK}:{path}", raise_on_progress=False)
                self._abort_if_unique_id_configured()
                self._data = {CONF_ACCOUNT_TYPE: TYPE_BANK, CONF_NAME: user_input[CONF_NAME].strip(),
                              CONF_FOLDER: user_input[CONF_FOLDER].strip(), CONF_USE_FINTS: user_input[CONF_USE_FINTS]}
                if user_input[CONF_USE_FINTS]:
                    return await self.async_step_fints_search()
                return self._finish(self._data[CONF_NAME])
        typed = user_input or {}
        return self.async_show_form(
            step_id="bank",
            data_schema=vol.Schema({vol.Required(CONF_NAME, default=typed.get(CONF_NAME, DEFAULT_BANK_NAME)): str,
                                    vol.Required(CONF_FOLDER, default=typed.get(CONF_FOLDER, DEFAULT_BANK_FOLDER)): str,
                                    vol.Required(CONF_USE_FINTS, default=typed.get(CONF_USE_FINTS, False)): bool}),
            errors=errors, description_placeholders={"config_dir": self.hass.config.config_dir},
        )

    async def async_step_fints_search(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Find the bank by name, bank code, or IBAN. Empty: enter everything by hand."""
        errors: dict[str, str] = {}
        if user_input is not None:
            query = (user_input.get(CONF_BANK_SEARCH) or "").strip()
            if not query:
                return await self.async_step_fints()
            hits = await self.hass.async_add_executor_job(banks.search, query)
            if len(hits) == 1:
                return await self._prefill(hits[0])
            if hits:
                self._bank_hits = hits
                return await self.async_step_fints_pick()
            errors[CONF_BANK_SEARCH] = "bank_not_found"
        return self.async_show_form(step_id="fints_search", errors=errors, data_schema=vol.Schema(
            {vol.Optional(CONF_BANK_SEARCH, default=""): str}))

    async def async_step_fints_pick(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return await self._prefill(next(h for h in self._bank_hits if h["blz"] == user_input[CONF_BLZ]))
        options = [selector.SelectOptionDict(value=h["blz"], label=f"{h['name']} ({h['blz']})") for h in self._bank_hits]
        return self.async_show_form(step_id="fints_pick", data_schema=vol.Schema({
            vol.Required(CONF_BLZ): selector.SelectSelector(selector.SelectSelectorConfig(options=options))}))

    async def _prefill(self, bank: dict) -> ConfigFlowResult:
        """Bank code from the search, and the server URL if the user's own FinTS bank list knows it."""
        paths = [Path(self.hass.config.path(banks.OWN_LIST)), Path(self.hass.config.path(DOMAIN, banks.OWN_LIST))]
        if self._data.get(CONF_FOLDER):
            paths.append(Path(self.hass.config.path(self._data[CONF_FOLDER], banks.OWN_LIST)))
        urls = await self.hass.async_add_executor_job(banks.own_urls, paths)
        self._data[CONF_BLZ] = bank["blz"]
        if bank["blz"] in urls:
            self._data[CONF_SERVER] = urls[bank["blz"]]
        self._bank_label = bank["name"]
        return await self.async_step_fints()

    async def _start_fints(self, data: dict[str, Any]) -> str | None:
        try:
            await async_process_requirements(self.hass, DOMAIN, list(FINTS_REQUIREMENTS))
        except RequirementsNotFound:
            return "install_failed"
        try:
            self._fints = await self.hass.async_add_executor_job(
                fints_client.start_login, data[CONF_BLZ], data[CONF_LOGIN], data[CONF_PIN], data[CONF_SERVER],
                data[CONF_PRODUCT_ID], fints_state_path(self.hass, data[CONF_BLZ], data[CONF_LOGIN]))
        except fints_client.FinTSUnreachable as err:
            _LOGGER.warning("No answer from the FinTS server %s", err)
            self._bank_reason = str(err)
            return "server_unreachable"
        except fints_client.FinTSBankError as err:
            _LOGGER.warning("The bank rejected the FinTS login: %s", err)
            self._bank_reason = str(err)
            return "bank_rejected"
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
            # Keep what was typed, so a rejected attempt does not mean entering everything again.
            # The PIN is the exception: it is never put back into a form.
            self._data.update({k: v for k, v in values.items() if k != CONF_PIN})
            if not values[CONF_BLZ].isdigit() or len(values[CONF_BLZ]) != 8:
                errors[CONF_BLZ] = "blz_format"
            elif not values[CONF_SERVER].startswith("https://"):
                errors[CONF_SERVER] = "server_format"
            elif len(values[CONF_PRODUCT_ID]) != 25:
                # The registration requires exactly the 25-character ID in HKVVB, nothing more or less.
                errors[CONF_PRODUCT_ID] = "product_id_format"
            elif err := await self._start_fints(values):
                errors["base"] = err
            else:
                self._data.update(values)
                return await self.async_step_fints_tan()
        bank = self._bank_label or banks.name_of(self._data.get(CONF_BLZ, "")) or ""
        return self.async_show_form(step_id="fints", data_schema=self._fints_schema(self._data), errors=errors,
                                    description_placeholders={"reason": self._bank_reason or "-", "bank": bank or "-"})

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

    # ------------------------------------------------------------ Energy and water

    async def async_step_utility(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        defaults = await energy_defaults(self.hass)
        if user_input is not None:
            utility = user_input[CONF_UTILITY]
            if utility == "gas" and not user_input.get(CONF_KWH_PER_M3):
                state = self.hass.states.get(user_input[CONF_STATISTIC])
                if state and state.attributes.get("unit_of_measurement") in ("m³", "m3"):
                    errors[CONF_KWH_PER_M3] = "kwh_per_m3_required"
            if not errors:
                await self.async_set_unique_id(f"{TYPE_UTILITY}:{user_input[CONF_STATISTIC]}", raise_on_progress=False)
                self._abort_if_unique_id_configured()
                self._data = {CONF_ACCOUNT_TYPE: TYPE_UTILITY, **user_input}
                return self._finish(user_input[CONF_NAME].strip() or utility.title())
        default_stat = next((defaults[t] for t in UTILITY_TYPES if defaults.get(t)), None)
        return self.async_show_form(step_id="utility", errors=errors, data_schema=vol.Schema({
            vol.Required(CONF_UTILITY, default="electricity"): selector.SelectSelector(selector.SelectSelectorConfig(
                options=UTILITY_TYPES, translation_key=CONF_UTILITY)),
            vol.Required(CONF_NAME, default=""): str,
            vol.Required(CONF_STATISTIC, description={"suggested_value": default_stat}): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class=["energy", "gas", "water"])),
            vol.Optional(CONF_KWH_PER_M3): selector.NumberSelector(selector.NumberSelectorConfig(
                min=1, max=20, step=0.001, mode=selector.NumberSelectorMode.BOX)),
        }))

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry: ConfigEntry) -> dict[str, type[ConfigSubentryFlow]]:
        if config_entry.data.get(CONF_ACCOUNT_TYPE) == TYPE_UTILITY:
            return {SUBENTRY_CONTRACT: ContractSubentryFlow}
        return {}

    # ------------------------------------------------------------ Overview

    async def async_step_overview(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            title = user_input[CONF_NAME].strip() or DEFAULT_OVERVIEW_TITLE
            # The first overview of earlier versions used the unique ID "overview".
            await self.async_set_unique_id(TYPE_OVERVIEW if title == DEFAULT_OVERVIEW_TITLE else f"{TYPE_OVERVIEW}:{title.lower()}", raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=title, data={CONF_ACCOUNT_TYPE: TYPE_OVERVIEW},
                                           options={CONF_MEMBERS: user_input.get(CONF_MEMBERS, [])})
        users = await _user_options(self.hass)
        return self.async_show_form(step_id="overview", data_schema=vol.Schema({
            vol.Required(CONF_NAME, default=DEFAULT_OVERVIEW_TITLE): str,
            vol.Optional(CONF_MEMBERS, default=[]): selector.SelectSelector(
                selector.SelectSelectorConfig(options=users, multiple=True)),
        }))

    # ------------------------------------------------------------ reauth

    def _owner_options(self) -> dict[str, Any]:
        """New accounts belong to the user who adds them."""
        user_id = self.context.get("user_id")
        return {CONF_OWNER: user_id} if user_id else {}

    def _finish(self, title: str) -> ConfigFlowResult:
        if self.source == SOURCE_REAUTH:
            return self.async_update_reload_and_abort(self._get_reauth_entry(), data_updates=self._data)
        return self.async_create_entry(title=title, data=self._data, options=self._owner_options())

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        self._data = dict(entry_data)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if vault.asks_for_pin(self._get_reauth_entry()):
            return await self.async_step_pin(user_input)
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
                                    errors=errors, description_placeholders={"reason": self._bank_reason or "-"})

    async def async_step_pin(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the PIN of an account that does not store it.

        Nothing is written: the PIN goes into memory and is gone after the next restart. It is
        entered twice, because a typo would reach the bank and count against the PIN attempts.
        """
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input[CONF_PIN] != user_input[CONF_PIN_CONFIRM]:
                errors[CONF_PIN_CONFIRM] = "pin_mismatch"
            else:
                vault.remember(self.hass, entry.entry_id, user_input[CONF_PIN])
                return self.async_update_reload_and_abort(entry, reason="pin_accepted")
        return self.async_show_form(step_id="pin", errors=errors, data_schema=vol.Schema(
            {vol.Required(CONF_PIN): PASSWORD, vol.Required(CONF_PIN_CONFIRM): PASSWORD}),
            description_placeholders={"account": entry.title})

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return FIOptionsFlow()


class FIOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._apply_pin_storage(user_input)
            return self.async_create_entry(data=user_input)
        opts = self.config_entry.options
        kind = self.config_entry.data.get(CONF_ACCOUNT_TYPE, TYPE_TRADE_REPUBLIC)
        users = await _user_options(self.hass)
        fields: dict = {}
        if kind == TYPE_OVERVIEW:
            fields[vol.Optional(CONF_MEMBERS, default=opts.get(CONF_MEMBERS, []))] = selector.SelectSelector(
                selector.SelectSelectorConfig(options=users, multiple=True))
        else:
            fields.update(_people_schema(users, opts.get(CONF_OWNER), opts.get(CONF_SHARED, [])))
        if kind == TYPE_UTILITY and self.config_entry.data.get(CONF_UTILITY) == "gas":
            fields[vol.Optional(CONF_KWH_PER_M3, description={"suggested_value": opts.get(
                CONF_KWH_PER_M3, self.config_entry.data.get(CONF_KWH_PER_M3))})] = selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=20, step=0.001, mode=selector.NumberSelectorMode.BOX))
        if kind != TYPE_OVERVIEW:
            fields[vol.Required(CONF_SCAN_MINUTES, default=opts.get(CONF_SCAN_MINUTES, DEFAULT_SCAN_MINUTES))] = \
                vol.All(vol.Coerce(int), vol.Range(min=5, max=1440))
        if kind == TYPE_TRADE_REPUBLIC:
            fields[vol.Required(CONF_TIMELINE_HOURS, default=opts.get(CONF_TIMELINE_HOURS, DEFAULT_TIMELINE_HOURS))] = \
                vol.All(vol.Coerce(int), vol.Range(min=1, max=168))
            fields[vol.Required(CONF_DIVIDEND_PROVIDER, default=opts.get(CONF_DIVIDEND_PROVIDER, "none"))] = \
                selector.SelectSelector(selector.SelectSelectorConfig(
                    options=DIVIDEND_PROVIDERS, translation_key=CONF_DIVIDEND_PROVIDER))
            fields[vol.Optional(CONF_DIVIDEND_API_KEY, description={"suggested_value": opts.get(CONF_DIVIDEND_API_KEY)})] = PASSWORD
            fields[vol.Required(CONF_YAHOO_FALLBACK, default=opts.get(CONF_YAHOO_FALLBACK, DEFAULT_MARKET_ONLINE))] = bool
            fields[vol.Required(CONF_BENCHMARKS, default=opts.get(CONF_BENCHMARKS, DEFAULT_MARKET_ONLINE))] = bool
            if self.config_entry.data.get(CONF_USE_PYTR):
                fields[vol.Required(CONF_WATCHLIST, default=opts.get(CONF_WATCHLIST, False))] = bool
            fields[vol.Required(CONF_MARKET_HOURS, default=opts.get(CONF_MARKET_HOURS, DEFAULT_MARKET_HOURS))] = \
                vol.All(vol.Coerce(int), vol.Range(min=6, max=168))
            joint = opts.get(CONF_TAX_JOINT, False)
            fields[vol.Required(CONF_TAX_ALLOWANCE, default=opts.get(CONF_TAX_ALLOWANCE, 2000 if joint else 1000))] = \
                _money_field(1)
            fields[vol.Optional(CONF_TAX_OTHER_INCOME, description={"suggested_value": opts.get(CONF_TAX_OTHER_INCOME)})] = \
                _money_field(1)
            fields[vol.Required(CONF_TAX_JOINT, default=joint)] = bool
            fields[vol.Required(CONF_TAX_CHURCH, default=opts.get(CONF_TAX_CHURCH, "0"))] = selector.SelectSelector(
                selector.SelectSelectorConfig(options=TAX_CHURCH_RATES, translation_key=CONF_TAX_CHURCH))
        if (kind == TYPE_BANK and self.config_entry.data.get(CONF_USE_FINTS)) or \
                (kind == TYPE_TRADE_REPUBLIC and self.config_entry.data.get(CONF_USE_PYTR)):
            fields[vol.Required(CONF_ASK_PIN, default=opts.get(CONF_ASK_PIN, False))] = bool
        if kind == TYPE_BANK:
            fields[vol.Required(CONF_FINTS_HOURS, default=opts.get(CONF_FINTS_HOURS, DEFAULT_FINTS_HOURS))] = \
                vol.All(vol.Coerce(int), vol.Range(min=1, max=168))
            fields[vol.Optional(CONF_TRANSFER_KEYWORDS, default=opts.get(CONF_TRANSFER_KEYWORDS, "Trade Republic"))] = str
            fields[vol.Optional(CONF_OFFSET_RULES, default=opts.get(CONF_OFFSET_RULES, ""))] = MULTILINE
        return self.async_show_form(step_id="init", data_schema=vol.Schema(fields))

    @callback
    def _apply_pin_storage(self, user_input: dict[str, Any]) -> None:
        """Move the PIN between the entry and memory when the option changes."""
        entry = self.config_entry
        wanted = user_input.get(CONF_ASK_PIN)
        if wanted is None or wanted == vault.asks_for_pin(entry):
            return
        if wanted:
            # Keep this session working, then take the PIN off the disk.
            if pin := entry.data.get(CONF_PIN):
                vault.remember(self.hass, entry.entry_id, pin)
            data = {k: v for k, v in entry.data.items() if k != CONF_PIN}
        elif pin := vault.pin(self.hass, entry):
            data = {**entry.data, CONF_PIN: pin}
        else:
            return  # nothing to write back; setup asks for the PIN again
        # Data and options change together. In between, the entry would have neither the stored
        # PIN nor the option that tells it to use the one in memory.
        self.hass.config_entries.async_update_entry(entry, data=data, options=dict(user_input))


def _money_field(step: float) -> selector.NumberSelector:
    return selector.NumberSelector(selector.NumberSelectorConfig(min=0, max=100000, step=step,
                                                                 mode=selector.NumberSelectorMode.BOX, unit_of_measurement="€"))


class ContractSubentryFlow(ConfigSubentryFlow):
    """A supply contract with prices and advance payments. Add a new one for every switch."""

    def _schema(self, d: dict) -> vol.Schema:
        unit = BILLING_UNIT[self._get_entry().data[CONF_UTILITY]]
        price = selector.NumberSelector(selector.NumberSelectorConfig(
            min=0, max=100, step="any", mode=selector.NumberSelectorMode.BOX, unit_of_measurement=f"€/{unit}"))

        def opt(key):
            return {"suggested_value": d.get(key)}

        return vol.Schema({
            vol.Required(CONF_SUPPLIER, description=opt(CONF_SUPPLIER)): str,
            vol.Required(CONF_START, description=opt(CONF_START)): selector.DateSelector(),
            vol.Optional(CONF_END, description=opt(CONF_END)): selector.DateSelector(),
            vol.Required(CONF_UNIT_PRICE, description=opt(CONF_UNIT_PRICE)): price,
            vol.Required(CONF_BASE_PRICE, default=d.get(CONF_BASE_PRICE, 0)): _money_field(0.01),
            vol.Required(CONF_ADVANCE, default=d.get(CONF_ADVANCE, 0)): _money_field(1),
            vol.Optional(CONF_BONUS, description=opt(CONF_BONUS)): _money_field(1),
            vol.Optional(CONF_NOTICE_WEEKS, description=opt(CONF_NOTICE_WEEKS)): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=52, step=1, mode=selector.NumberSelectorMode.BOX)),
        })

    @staticmethod
    def _errors(user_input: dict) -> dict[str, str]:
        if user_input.get(CONF_END) and user_input[CONF_END] < user_input[CONF_START]:
            return {CONF_END: "end_before_start"}
        return {}

    @staticmethod
    def _title(user_input: dict) -> str:
        return f"{user_input[CONF_SUPPLIER].strip()} ({user_input[CONF_START]})"

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        errors = self._errors(user_input) if user_input is not None else {}
        if user_input is not None and not errors:
            return self.async_create_entry(title=self._title(user_input), data=user_input)
        return self.async_show_form(step_id="user", data_schema=self._schema(user_input or {}), errors=errors)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        subentry = self._get_reconfigure_subentry()
        errors = self._errors(user_input) if user_input is not None else {}
        if user_input is not None and not errors:
            return self.async_update_and_abort(self._get_entry(), subentry, title=self._title(user_input), data=user_input)
        return self.async_show_form(step_id="reconfigure", data_schema=self._schema(user_input or dict(subentry.data)),
                                    errors=errors)
