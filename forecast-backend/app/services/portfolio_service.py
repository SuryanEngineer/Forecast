"""
Bulk net-worth computation shared by the leaderboards, daily snapshots, seasons and stats.

net worth = wallet cash (includes cash reserved for open buy orders) + shares x last traded price
            + treasury holdings (principal + accrued interest).
"""
from __future__ import annotations

import time
import uuid
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.models.bot import BotProfile
from app.models.player import Player, Position, PriceSnapshot
from app.models.treasury import TreasuryHolding, TreasuryHoldingStatus
from app.models.user import User
from app.models.wallet import Wallet
from app.services.house_account import HOUSE_ACCOUNT_EMAIL

ZERO = Decimal("0")
_CACHE: dict[str, tuple[float, dict]] = {}
CACHE_TTL_SECONDS = 10.0


def last_prices(db: Session) -> dict[uuid.UUID, Decimal]:
    """Latest trade price per player (IPO price when never traded)."""
    newest = (
        db.query(PriceSnapshot.player_id.label("pid"), func.max(PriceSnapshot.recorded_at).label("m"))
        .group_by(PriceSnapshot.player_id).subquery()
    )
    prices: dict[uuid.UUID, Decimal] = {}
    for pid, price in (
        db.query(PriceSnapshot.player_id, PriceSnapshot.price)
        .join(newest, and_(PriceSnapshot.player_id == newest.c.pid, PriceSnapshot.recorded_at == newest.c.m))
        .all()
    ):
        prices[pid] = price
    for pid, ipo in db.query(Player.id, Player.ipo_price).all():
        prices.setdefault(pid, ipo)
    return prices


def eligible_user_ids(db: Session, include_bots: bool = True) -> list[uuid.UUID]:
    q = db.query(User.id).filter(User.email != HOUSE_ACCOUNT_EMAIL, User.is_active.is_(True))
    if not include_bots:
        q = q.filter(User.id.notin_(select(BotProfile.user_id)))
    return [uid for (uid,) in q.all()]


def compute_net_worths(db: Session, user_ids: list[uuid.UUID] | None = None, include_bots: bool = True) -> dict[uuid.UUID, dict[str, Decimal]]:
    """{user_id: {cash, holdings, treasury, net_worth}} for the given users (default: every real+bot user)."""
    ids = set(user_ids) if user_ids is not None else set(eligible_user_ids(db, include_bots))
    if not ids:
        return {}
    prices = last_prices(db)
    out: dict[uuid.UUID, dict[str, Decimal]] = {uid: {"cash": ZERO, "holdings": ZERO, "treasury": ZERO} for uid in ids}

    for uid, cash in db.query(Wallet.user_id, Wallet.cash_balance).all():
        if uid in out:
            out[uid]["cash"] = cash
    for uid, pid, qty in db.query(Position.user_id, Position.player_id, Position.quantity).filter(Position.quantity > 0).all():
        if uid in out:
            out[uid]["holdings"] += prices.get(pid, ZERO) * qty
    for uid, principal, accrued in db.query(
        TreasuryHolding.user_id, TreasuryHolding.principal_amount, TreasuryHolding.accrued_interest
    ).filter(TreasuryHolding.status == TreasuryHoldingStatus.ACTIVE).all():
        if uid in out:
            out[uid]["treasury"] += principal + accrued
    for v in out.values():
        v["net_worth"] = v["cash"] + v["holdings"] + v["treasury"]
    return out


def compute_net_worths_cached(db: Session, include_bots: bool = True) -> dict[uuid.UUID, dict[str, Decimal]]:
    """Everyone's net worth, memoised for a few seconds -- leaderboard endpoints get hit by every open tab."""
    key = f"all:{include_bots}"
    hit = _CACHE.get(key)
    now = time.monotonic()
    if hit is not None and now - hit[0] < CACHE_TTL_SECONDS:
        return hit[1]
    data = compute_net_worths(db, None, include_bots)
    _CACHE[key] = (now, data)
    return data


def clear_cache() -> None:
    _CACHE.clear()
