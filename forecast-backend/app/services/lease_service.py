"""
Single-writer lease for the matching engine.

The order books and the reference-price cache live in the memory of the web-server process, so exactly ONE process may
match orders at a time. Two writers (a second Render instance after scaling up, a deploy overlap, a script that trades)
would each hold a stale copy of the books and could fill the same resting order twice or miss each other's orders.

How it works: a row in `market_lease` ('market') names the holder and an expiry. The server renews it every
HEARTBEAT_SECONDS; a process that cannot renew stops being primary once its validity runs out (safely BEFORE the row
expires, see SAFETY_MARGIN) and the next process to ask takes over. On a clean shutdown the lease is released at once,
so a deploy hands over in seconds.

  * the primary runs the bots, maintenance (dividends, seasons), Osirion sync, retention and matches orders;
  * every other server instance still serves reads, but order changes get a clear 'market is busy' error (HTTP 400);
  * scripts that change market state call `script_guard_or_exit` first and refuse to run while a server holds the lease.

Disabled (always primary) for SQLite/demo or with MARKET_LEASE_ENABLED=false. Outside a server process (scripts, tests)
nothing is enforced on order calls.
"""
from __future__ import annotations

import logging
import os
import socket
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.exceptions import NotPrimaryError

log = logging.getLogger("forecast.lease")

NAME = "market"
LEASE_SECONDS = 60
HEARTBEAT_SECONDS = 15
SAFETY_MARGIN = 10          # stop acting as primary this many seconds before the row could expire
HOLDER = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"

_state = {"held": False, "valid_until": 0.0, "server": False}


def enabled() -> bool:
    if getattr(settings, "DEMO_MODE", False):
        return False
    if str(settings.DATABASE_URL).startswith("sqlite"):
        return False
    return bool(getattr(settings, "MARKET_LEASE_ENABLED", True))


def mark_server() -> None:
    """Called once by the web app's startup: from now on order changes require the lease."""
    _state["server"] = True


def holds_lease() -> bool:
    if not enabled():
        return True
    return bool(_state["held"]) and time.monotonic() < _state["valid_until"]


def require_primary() -> None:
    """Order entry/cancel call this. Only enforced inside the web server."""
    if _state["server"] and not holds_lease():
        raise NotPrimaryError(
            "The market is switching servers for a moment (a deploy or restart is in progress) -- try again in a few seconds."
        )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def acquire_or_renew(db: Session) -> bool:
    """Take the lease if it is free/expired or already ours; otherwise leave it. Returns whether we hold it now."""
    if not enabled():
        _state.update(held=True, valid_until=float("inf"))
        return True
    now = _utcnow()
    was_held = holds_lease()
    res = db.execute(
        text(
            "INSERT INTO market_lease (name, holder, expires_at, updated_at) VALUES (:n, :h, :e, :now) "
            "ON CONFLICT (name) DO UPDATE SET holder = :h, expires_at = :e, updated_at = :now "
            "WHERE market_lease.holder = :h OR market_lease.expires_at < :now"
        ),
        {"n": NAME, "h": HOLDER, "e": now + timedelta(seconds=LEASE_SECONDS), "now": now},
    )
    db.commit()
    got = (res.rowcount or 0) > 0
    if got:
        if not was_held:
            # We are (again) the writer: whatever we cached while someone else was writing is stale.
            from app.services import book_registry, reference_service

            book_registry.reset_book_cache()
            reference_service.reset()
            log.info("Market lease acquired by %s", HOLDER)
        _state.update(held=True, valid_until=time.monotonic() + LEASE_SECONDS - SAFETY_MARGIN)
    else:
        if _state["held"]:
            log.warning("Market lease lost -- this instance stops matching orders")
        _state.update(held=False, valid_until=0.0)
    return got


def release(db: Session) -> None:
    """Hand the lease over immediately (clean shutdown)."""
    if not enabled():
        return
    try:
        db.execute(
            text("UPDATE market_lease SET expires_at = :past WHERE name = :n AND holder = :h"),
            {"n": NAME, "h": HOLDER, "past": _utcnow() - timedelta(seconds=1)},
        )
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
    _state.update(held=False, valid_until=0.0)


def current_holder(db: Session) -> tuple[str, datetime] | None:
    row = db.execute(text("SELECT holder, expires_at FROM market_lease WHERE name = :n"), {"n": NAME}).first()
    if row is None:
        return None
    exp = row[1]
    if isinstance(exp, str):
        exp = datetime.fromisoformat(exp)
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return row[0], exp


def script_guard_or_exit(db: Session, script_name: str) -> None:
    """For scripts that trade or rewrite prices: they would work on a private copy of the order books, so refuse while a
    web server holds the lease (suspend the Render service first). Safe no-op when the lease is disabled."""
    if not enabled():
        return
    try:
        cur = current_holder(db)
    except Exception:  # noqa: BLE001  -- table missing (migration not run yet): nothing is guarding, carry on
        db.rollback()
        return
    if cur is not None and cur[1] > _utcnow() and cur[0] != HOLDER:
        print(
            f"\n{script_name}: a web server ({cur[0]}) currently runs the market (lease valid until {cur[1].isoformat()}).\n"
            "This script would change prices/orders behind its back. In Render: suspend the backend service, wait ~1 minute\n"
            "for the lease to expire, run the script, then resume the service.\n"
        )
        sys.exit(2)
