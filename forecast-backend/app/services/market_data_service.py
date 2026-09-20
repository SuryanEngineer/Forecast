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


def _bulk_latest_prices(
    db: Session, player_ids: list[uuid.UUID], before: datetime | None = None
) -> dict[uuid.UUID, Decimal]:
    """Each player's most recent PriceSnapshot price (optionally as of
    some cutoff time) in ONE query, instead of one query per player --
    see list_market_snapshots' docstring for why this matters. Uses
    ROW_NUMBER() OVER (PARTITION BY player_id ...) rather than a plain
    GROUP BY MAX(recorded_at), since what's needed is the PRICE at that
    latest timestamp, not just the timestamp itself. Window functions
    work the same way on Postgres and on SQLite (supported there since
    3.25, released 2018), so this is safe in both real and demo mode."""
    if not player_ids:
        return {}
    row_number = func.row_number().over(
        partition_by=PriceSnapshot.player_id,
        order_by=PriceSnapshot.recorded_at.desc(),
    ).label("rn")
    ranked = db.query(PriceSnapshot.player_id, PriceSnapshot.price, row_number).filter(
        PriceSnapshot.player_id.in_(player_ids)
    )
    if before is not None:
        ranked = ranked.filter(PriceSnapshot.recorded_at <= before)
    ranked_subquery = ranked.subquery()

    rows = db.query(ranked_subquery.c.player_id, ranked_subquery.c.price).filter(ranked_subquery.c.rn == 1).all()
    return {player_id: price for player_id, price in rows}


def _bulk_volume_since(db: Session, player_ids: list[uuid.UUID], since: datetime) -> dict[uuid.UUID, int]:
    """Each player's total traded quantity since `since` in ONE query --
    see list_market_snapshots' docstring."""
    if not player_ids:
        return {}
    rows = (
        db.query(Trade.player_id, func.coalesce(func.sum(Trade.quantity), 0))
        .filter(Trade.player_id.in_(player_ids), Trade.executed_at >= since)
        .group_by(Trade.player_id)
        .all()
    )
    return {player_id: int(total or 0) for player_id, total in rows}


def list_market_snapshots(db: Session, active_only: bool = True) -> list[dict]:
    """Batch-computed equivalent of calling get_market_snapshot() once per
    player. That naive per-player loop meant THREE separate DB
    round-trips per player (last price, price-24h-ago, 24h volume) -- for
    a roster in the hundreds, that's 450+ sequential queries on every
    single GET /markets request. Beyond just being slow, that's a real
    risk of the request timing out under load or right after a cold
    start on a single free-tier instance -- which surfaces to users as a
    generic, confusing "Failed to fetch" with no HTTP status to point to,
    since the connection gets dropped before any response is sent. This
    does the exact same three lookups, but as three bulk queries total,
    no matter how large the roster is."""
    query = db.query(Player)
    if active_only:
        query = query.filter(Player.is_active.is_(True))
    players = query.order_by(Player.gamertag.asc()).all()
    if not players:
        return []

    player_ids = [p.id for p in players]
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(hours=24)

    last_prices = _bulk_latest_prices(db, player_ids)
    prev_prices = _bulk_latest_prices(db, player_ids, before=day_ago)
    volumes = _bulk_volume_since(db, player_ids, day_ago)

    snapshots: list[dict] = []
    for player in players:
        last_price = last_prices.get(player.id, player.ipo_price)
        # Same "never traded before the 24h window" fallback as
        # get_market_snapshot above: treat the reference price as the
        # current price (0% change) rather than comparing against a
        # possibly arbitrarily-old IPO price.
        prev_close = prev_prices.get(player.id, last_price)
        change = last_price - prev_close
        change_pct = (change / prev_close * 100) if prev_close > 0 else Decimal("0")
        snapshots.append(
            {
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
                "volume_24h": volumes.get(player.id, 0),
                "market_cap": last_price * player.total_shares_outstanding,
            }
        )
    return snapshots


def get_price_history(db: Session, player_id: uuid.UUID, limit: int = 200) -> list[PriceSnapshot]:
    rows = (
        db.query(PriceSnapshot)
        .filter(PriceSnapshot.player_id == player_id)
        .order_by(PriceSnapshot.recorded_at.desc())
        .limit(limit)
        .all()
    )
    return list(reversed(rows))  # oldest first, chart-ready
