"""Blocking wrapper around pytr. Every function here runs in an executor thread.

pytr is imported lazily so the integration works without it in CSV-only mode.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

_LOGGER = logging.getLogger(__name__)


class PytrAuthError(Exception):
    """The saved session is gone; the user has to log in again."""


class PytrNotConfirmed(Exception):
    """The login push notification was not confirmed yet."""


def _api(phone: str, pin: str, cookies_file: Path):
    from pytr.api import TradeRepublicApi

    cookies_file.parent.mkdir(parents=True, exist_ok=True)
    return TradeRepublicApi(phone_no=phone, pin=pin, save_cookies=True,
                            cookies_file=str(cookies_file), use_v2_login=True)


def start_login(phone: str, pin: str, cookies_file: Path):
    """Start the v2 web login. Returns (api, needs_authenticator_code)."""
    api = _api(phone, pin, cookies_file)
    api.initiate_weblogin()
    return api, api.weblogin_needs_authenticator


def finish_login(api, code: str | None) -> None:
    """Complete the login after the push was confirmed or with an authenticator code."""
    if api.weblogin_needs_authenticator:
        api.complete_weblogin(code)
        return
    # Poll once instead of blocking the flow for up to two minutes.
    status = api._get_weblogin_process().get("status")  # noqa: SLF001 - pytr has no public accessor
    if status == "PENDING":
        raise PytrNotConfirmed
    api.complete_weblogin()


def _newest_event_ts(db: Path) -> float | None:
    if not db.exists():
        return None
    try:
        events = json.loads(db.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    stamps = [datetime.fromisoformat(e["timestamp"][:19]).timestamp() for e in events if e.get("timestamp")]
    return max(stamps) if stamps else None


def load_events(work_dir: Path) -> list[dict]:
    db = work_dir / "all_events.json"
    if not db.exists():
        return []
    try:
        return json.loads(db.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _LOGGER.warning("Could not read %s", db)
        return []


async def bond_mid_prices(api, positions: list[dict], timeout: float = 5.0) -> None:
    """Replace the last-trade price of bonds with the middle of bid and ask.

    Bond quotes are thin: the last trade can be far off (for example 10 % on a
    bond that trades around 108 %). Bid and ask are kept up to date by the market
    maker, so their middle is a steadier value. Prices are in percent, stored as
    a fraction like pytr does.
    """
    from pytr.tickers import bond_pattern

    subs = {}
    for pos in positions:
        if pos.get("exchangeIds") and bond_pattern.search(pos.get("name", "")):
            sub_id = await api.ticker(pos["instrumentId"], exchange=pos["exchangeIds"][0])
            subs[sub_id] = pos
    while subs:
        try:
            sub_id, subscription, response = await asyncio.wait_for(api.recv(), timeout)
        except asyncio.TimeoutError:
            _LOGGER.debug("No bid/ask for %s", [p["instrumentId"] for p in subs.values()])
            break
        if subscription.get("type") != "ticker" or sub_id not in subs:
            continue
        await api.unsubscribe(sub_id)
        pos = subs.pop(sub_id)
        bid = (response.get("bid") or {}).get("price")
        ask = (response.get("ask") or {}).get("price")
        if bid and ask:
            pos["price"] = (float(bid) + float(ask)) / 200
    await api.close()


def fetch(phone: str, pin: str, cookies_file: Path, work_dir: Path,
          csv_cutoff: str | None, with_timeline: bool, timeout: float = 600) -> dict:
    """Resume the session, optionally update the event database, and read
    current positions, prices, and cash."""
    from pytr.api import TradeRepublicApi  # noqa: F401 - fail early if missing
    from pytr.portfolio import Portfolio
    from pytr.timeline import Timeline

    api = _api(phone, pin, cookies_file)
    if not api.resume_websession():
        raise PytrAuthError("Trade Republic session expired")

    work_dir.mkdir(parents=True, exist_ok=True)
    newest = _newest_event_ts(work_dir / "all_events.json")
    if newest is None and csv_cutoff:
        newest = datetime.fromisoformat(csv_cutoff[:19]).timestamp()
    # Re-read a few days so late corrections land in the database.
    not_before = (newest - timedelta(days=3).total_seconds()) if newest else 0.0

    async def run():
        # pytr keeps these at class level; give this run its own copies so
        # repeated runs in fresh event loops do not share state.
        api._lock = asyncio.Lock()  # noqa: SLF001
        api.subscriptions = {}
        api._previous_responses = {}  # noqa: SLF001
        if with_timeline:
            tl = Timeline(api, work_dir, not_before=not_before, store_event_database=True)
            await tl.tl_loop()
        pf = Portfolio(api)
        await pf.portfolio_loop()
        await bond_mid_prices(api, pf.positions)
        return pf

    pf = asyncio.run(asyncio.wait_for(run(), timeout))
    positions = [
        dict(isin=p["instrumentId"], name=p.get("name"), shares=float(p["netSize"]),
             avg_cost=float(p["averageBuyIn"]) if p.get("averageBuyIn") is not None else None,
             price=float(p["price"]))
        for p in pf.positions if "price" in p
    ]
    cash = None
    for c in getattr(pf, "cash", None) or []:
        if c.get("currencyId") == "EUR":
            cash = float(c["amount"])
    return dict(positions=positions, cash=cash, timeline_updated=with_timeline)
