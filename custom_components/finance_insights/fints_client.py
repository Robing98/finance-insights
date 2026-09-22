"""Blocking wrapper around python-fints. Every function runs in an executor thread.

The FinTS product registration number is entered by the user.
"""
from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

_LOGGER = logging.getLogger(__name__)


class FinTSAuthRequired(Exception):
    """The bank wants a new TAN confirmation (strong customer authentication)."""


class FinTSNotConfirmed(Exception):
    """The pushTAN was not confirmed yet."""


class FinTSBankError(Exception):
    """The bank rejected the request. str() holds the bank's own messages, for example
    9010 plus the reason, so the user sees why instead of a generic error."""


class _Collector(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        code = getattr(record, "fints_response_code", None)
        if code:
            text = f"{code} {getattr(record, 'fints_response_text', '')}".strip()
            if text not in self.messages:
                self.messages.append(text)


@contextmanager
def _bank_messages():
    """Turn python-fints errors into FinTSBankError with the bank's warnings and errors."""
    collector = _Collector()
    log = logging.getLogger("fints")
    log.addHandler(collector)
    try:
        yield
    except (FinTSNotConfirmed, FinTSAuthRequired):
        raise
    except Exception as err:
        if collector.messages:
            raise FinTSBankError("; ".join(collector.messages[-4:])) from err
        raise
    finally:
        log.removeHandler(collector)


def _client(blz: str, login: str, pin: str, server: str, product_id: str, state_file: Path | None):
    from fints.client import FinTS3PinTanClient

    blob = state_file.read_bytes() if state_file and state_file.exists() else None
    return FinTS3PinTanClient(blz, login, pin, server, product_id=product_id, product_version=product_version(),
                              from_data=blob)


def product_version() -> str:
    """FinTS wants the version of this software (max. 5 characters), not the library version."""
    manifest = json.loads((Path(__file__).parent / "manifest.json").read_text(encoding="utf-8"))
    return manifest["version"][:5]


def _save(client, state_file: Path) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_bytes(client.deconstruct(including_private=True))


def _bootstrap(client) -> None:
    """Pick a TAN method without asking: prefer decoupled app methods (pushTAN)."""
    if not client.get_current_tan_mechanism():
        client.fetch_tan_mechanisms()
        mechanisms = list(client.get_tan_mechanisms().items())
        if len(mechanisms) > 1:
            push = [m for m in mechanisms if "push" in (m[1].name or "").lower() or "app" in (m[1].name or "").lower()]
            client.set_tan_mechanism((push or mechanisms)[0][0])
    if client.selected_tan_medium is None and client.is_tan_media_required():
        media = client.get_tan_media()[1]
        if len(media) >= 1:
            client.set_tan_medium(media[0])
        else:
            client.selected_tan_medium = ""


class LoginSession:
    """Holds a started login between config flow steps."""

    def __init__(self, client, challenge, dialog_data, state_file: Path) -> None:
        self.client = client
        self.challenge = challenge
        self.dialog_data = dialog_data
        self.state_file = state_file

    @property
    def decoupled(self) -> bool:
        return bool(self.challenge is None or self.challenge.decoupled)

    @property
    def challenge_text(self) -> str:
        return (getattr(self.challenge, "challenge", None) or "").strip()


def start_login(blz, login, pin, server, product_id, state_file: Path) -> LoginSession:
    with _bank_messages():
        client = _client(blz, login, pin, server, product_id, None)
        _bootstrap(client)
        with client:
            challenge = client.init_tan_response
            dialog_data = client.pause_dialog()
    return LoginSession(client, challenge, dialog_data, state_file)


def finish_login(session: LoginSession, tan: str | None) -> list[str]:
    """Confirm the TAN, then return the IBANs of all accounts."""
    from fints.client import NeedTANResponse

    client = session.client
    with client.resume_dialog(session.dialog_data):
        if session.challenge is not None:
            result = client.send_tan(session.challenge, tan or "")
            if isinstance(result, NeedTANResponse):
                session.challenge = result
                session.dialog_data = client.pause_dialog()
                raise FinTSNotConfirmed
        accounts = client.get_sepa_accounts()
        if isinstance(accounts, NeedTANResponse):
            session.challenge = accounts
            session.dialog_data = client.pause_dialog()
            raise FinTSNotConfirmed
    _save(client, session.state_file)
    return [a.iban for a in accounts]


def fetch(blz, login, pin, server, product_id, state_file: Path, iban: str, days: int = 85) -> dict:
    """Balance and transactions of the last `days` days. Most banks allow up to
    90 days without a new TAN."""
    from fints.client import NeedTANResponse

    client = _client(blz, login, pin, server, product_id, state_file)
    with client:
        if client.init_tan_response:
            raise FinTSAuthRequired
        accounts = client.get_sepa_accounts()
        if isinstance(accounts, NeedTANResponse):
            raise FinTSAuthRequired
        account = next((a for a in accounts if a.iban.replace(" ", "") == iban), None)
        if account is None:
            raise ValueError(f"Account {iban[-4:]} not found at the bank")
        balance = client.get_balance(account)
        if isinstance(balance, NeedTANResponse):
            raise FinTSAuthRequired
        transactions = client.get_transactions(account, date.today() - timedelta(days=days), date.today())
        if isinstance(transactions, NeedTANResponse):
            raise FinTSAuthRequired
    _save(client, state_file)
    amount = getattr(balance, "amount", None)
    value = float(getattr(amount, "amount", amount)) if amount is not None else None
    return {"balance": value, "balance_date": getattr(balance, "date", None), "transactions": transactions}
