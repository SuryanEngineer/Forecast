"""
Read-side market data: turns raw Trade/PriceSnapshot history into the
"last price / 24h change / 24h volume / market cap" view every trading
UI needs. Nothing here writes anything -- it's a reporting layer on top
of data order_service.py and auction_service.py already produce.

*** PLACEHOLDER DEFINITION -- read this before trusting the numbers ***
"24h change" here means "change since the closest PriceSnapshot at or
before 24 hours ago," which is the standard definition real exchanges
use, but for a player that hasn't traded in the last day the "24h ago"
snapshot might actually be several days old -- this is a simplification,
not a bug, and matches the roadmap's "correct and testable, not yet
production-hardened" phase.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.player import Player, PriceSnapshot
from app.models.order import Trade


def _last_price(db: Session, player: Player) -> Decimal:
    snapshot = (
        db.query(PriceSnapshot)
        .filter(PriceSnapshot.player_id == player.id)
        .order_by(PriceSnapshot.recorded_at.desc())
        .first()
    )
    return snapshot.price if snapshot is not None else player.ipo_price


def _price_as_of(db: Session, player_id: uuid.UUID, as_of: datetime) -> Decimal | None:
    snapshot = (
        db.query(PriceSnapshot)
        .filter(PriceSnapshot.player_id == player_id, PriceSnapshot.recorded_at <= as_of)
        .order_by(PriceSnapshot.recorded_at.desc())
        .first()
    )
    return snapshot.price if snapshot is not None else None


def _volume_since(db: Session, player_id: uuid.UUID, since: datetime) -> int:
    total = (
        db.query(func.coalesce(func.sum(Trade.quantity), 0))
        .filter(Trade.player_id == player_id, Trade.executed_at >= since)
        .scalar()
    )
    return int(total or 0)


def get_market_snapshot(db: Session, player: Player) -> dict:
    """One player's current trading view: last price, prior-24h reference
    price, absolute/percent change, 24h volume, and market cap."""
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(hours=24)

    last_price = _last_price(db, player)
    prev_close = _price_as_of(db, player.id, day_ago)
    if prev_close is None:
        # Never traded before the 24h window -- no meaningful "change" yet,
        # so treat the reference price as the current price (0% change)
        # rather than inventing a comparison against the IPO price, which
        # could be an arbitrarily long time ago.
        prev_close = last_price

    change = last_price - prev_close
    change_pct = (change / prev_close * 100) if prev_close > 0 else Decimal("0")
    volume_24h = _volume_since(db, player.id, day_ago)
    market_cap = last_price * player.total_shares_outstanding

    return {
        "id": player.id,
        "gamertag": player.gamertag,
        "real_name": player.real_name,
        "team": player.team,
        "region": player.region,
        "total_shares_outstanding": player.total_shares_outstanding,
        "ipo_price": player.ipo_price,
        "last_price": last_price,
        "prev_close": prev_close,
        "change": change,
        "change_pct": change_pct,
        "volume_24h": volume_24h,
        "market_cap": market_cap,
    }


def list_market_snapshots(db: Session, active_only: bool = True) -> list[dict]:
    query = db.query(Player)
    if active_only:
        query = query.filter(Player.is_active.is_(True))
    players = query.order_by(Player.gamertag.asc()).all()
    return [get_market_snapshot(db, p) for p in players]


def get_price_history(db: Session, player_id: uuid.UUID, limit: int = 200) -> list[PriceSnapshot]:
    rows = (
        db.query(PriceSnapshot)
        .filter(PriceSnapshot.player_id == player_id)
        .order_by(PriceSnapshot.recorded_at.desc())
        .limit(limit)
        .all()
    )
    return list(reversed(rows))  # oldest first, chart-ready
