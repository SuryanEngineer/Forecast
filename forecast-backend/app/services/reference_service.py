"""
The stored REFERENCE PRICE of every stock (see app/engine/market_policy.py for what it means).

Persisted in players.reference_price; kept in a process-local cache so the order flow, the bots and the market screens
read it for free (a per-tick database read of ~900 rows would burn Supabase egress). The server process that holds the
market lease (see lease_service) is the only writer, so its cache is authoritative and never expires; any other process
(scripts, a stray second instance) re-reads from the database every REFRESH_SECONDS.

Updates made inside a database transaction become visible to other readers only once the transaction COMMITS: they are
parked on the session and applied by an after_commit hook (dropped on rollback), so a failed order can never leave the
cache ahead of the database. Reads inside the same transaction see the pending values.
"""
from __future__ import annotations

import time
import uuid
from decimal import Decimal

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.models.player import Player

REFRESH_SECONDS = 15.0
_CACHE: dict[uuid.UUID, Decimal] = {}
_STATE = {"loaded_at": 0.0}


def _authoritative() -> bool:
    from app.services import lease_service

    return lease_service.holds_lease()


def reset() -> None:
    """Forget the cache (tests, and scripts that rewrite prices behind the server's back)."""
    _CACHE.clear()
    _STATE["loaded_at"] = 0.0


def _load(db: Session) -> None:
    from app.services import market_data_service

    rows = db.query(Player.id, Player.reference_price, Player.ipo_price).all()
    missing = [pid for pid, ref, _ipo in rows if ref is None]
    last = market_data_service._bulk_latest_prices(db, missing) if missing else {}
    fresh: dict[uuid.UUID, Decimal] = {}
    for pid, ref, ipo in rows:
        fresh[pid] = ref if ref is not None else last.get(pid, ipo)
    _CACHE.clear()
    _CACHE.update(fresh)
    _STATE["loaded_at"] = time.monotonic()


def _ensure(db: Session) -> None:
    if not _STATE["loaded_at"]:
        _load(db)
        return
    if not _authoritative() and time.monotonic() - _STATE["loaded_at"] > REFRESH_SECONDS:
        _load(db)


def get_ref(db: Session, player_id: uuid.UUID, fallback: Decimal | None = None) -> Decimal | None:
    """Reference price of one stock (pending, uncommitted updates of this session included)."""
    pending = db.info.get("pending_refs")
    if pending and player_id in pending:
        return pending[player_id]
    _ensure(db)
    if player_id not in _CACHE:
        _load_one(db, player_id)  # a stock created after the cache was filled
    return _CACHE.get(player_id, fallback)


def _load_one(db: Session, player_id: uuid.UUID) -> None:
    from app.services import market_data_service

    row = db.query(Player.reference_price, Player.ipo_price).filter(Player.id == player_id).one_or_none()
    if row is None:
        return
    ref, ipo = row
    if ref is None:
        ref = market_data_service._bulk_latest_prices(db, [player_id]).get(player_id, ipo)
    _CACHE[player_id] = ref


def get_refs(db: Session, player_ids: list[uuid.UUID] | None = None) -> dict[uuid.UUID, Decimal]:
    _ensure(db)
    out = dict(_CACHE) if player_ids is None else {pid: _CACHE[pid] for pid in player_ids if pid in _CACHE}
    pending = db.info.get("pending_refs")
    if pending:
        for pid, v in pending.items():
            if player_ids is None or pid in set(player_ids):
                out[pid] = v
    return out


def set_ref(db: Session, player_id: uuid.UUID, value: Decimal) -> None:
    """Write the new reference price (flushes to the row now; the cache follows on commit). Caller commits."""
    value = max(Decimal("0.01"), Decimal(value)).quantize(Decimal("0.0001"))
    db.query(Player).filter(Player.id == player_id).update({Player.reference_price: value}, synchronize_session=False)
    db.info.setdefault("pending_refs", {})[player_id] = value


@event.listens_for(Session, "after_commit")
def _apply_pending(session: Session) -> None:
    pending = session.info.pop("pending_refs", None)
    if pending:
        _CACHE.update(pending)


@event.listens_for(Session, "after_rollback")
def _drop_pending(session: Session) -> None:
    session.info.pop("pending_refs", None)
