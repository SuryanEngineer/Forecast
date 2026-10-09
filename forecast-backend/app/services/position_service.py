"""
Position (share holding) operations -- the share-side mirror of
wallet_service.py's cash operations. Same convention: functions here
`db.flush()` but never `db.commit()`.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.player import Position, ShareTransfer
from app.services.exceptions import InsufficientSharesError


def get_or_create_position(db: Session, user_id: uuid.UUID, player_id: uuid.UUID) -> Position:
    position = (
        db.query(Position)
        .filter(Position.user_id == user_id, Position.player_id == player_id)
        .with_for_update()
        .one_or_none()
    )
    if position is None:
        position = Position(user_id=user_id, player_id=player_id, quantity=0, held_quantity=0, average_cost=Decimal("0"))
        db.add(position)
        db.flush()
    return position


def hold_shares(db: Session, user_id: uuid.UUID, player_id: uuid.UUID, quantity: int) -> Position:
    """Reserve `quantity` shares against a newly-placed limit sell order."""
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    position = get_or_create_position(db, user_id, player_id)
    if position.available_quantity < quantity:
        raise InsufficientSharesError(
            f"user has {position.available_quantity} available shares of player {player_id}, needs {quantity}"
        )
    position.held_quantity += quantity
    db.flush()
    return position


def release_shares(db: Session, user_id: uuid.UUID, player_id: uuid.UUID, quantity: int) -> Position:
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    position = get_or_create_position(db, user_id, player_id)
    release_qty = min(quantity, position.held_quantity)
    position.held_quantity -= release_qty
    db.flush()
    return position


def transfer_shares_for_trade(
    db: Session,
    buyer_user_id: uuid.UUID,
    seller_user_id: uuid.UUID,
    player_id: uuid.UUID,
    quantity: int,
    trade_price: Decimal,
) -> None:
    """Move `quantity` shares from seller to buyer as part of settling a
    Trade. Seller's held_quantity (reserved at sell-order-placement time)
    is released here since the shares are now actually gone. Buyer's
    average_cost is updated as a running weighted average for P&L
    display purposes only."""
    if quantity <= 0:
        raise ValueError("quantity must be positive")

    seller_position = get_or_create_position(db, seller_user_id, player_id)
    seller_position.quantity -= quantity
    seller_position.held_quantity = max(0, seller_position.held_quantity - quantity)

    buyer_position = get_or_create_position(db, buyer_user_id, player_id)
    existing_notional = buyer_position.average_cost * buyer_position.quantity
    new_notional = existing_notional + (trade_price * quantity)
    new_quantity = buyer_position.quantity + quantity
    buyer_position.average_cost = (new_notional / new_quantity) if new_quantity > 0 else Decimal("0")
    buyer_position.quantity = new_quantity

    # Timestamped ledger (see ShareTransfer) -- lets dividends be paid on what each user held at a
    # tournament's START rather than whatever they hold when the payout job happens to run.
    db.add(ShareTransfer(id=uuid.uuid4(), user_id=seller_user_id, player_id=player_id, delta=-quantity))
    db.add(ShareTransfer(id=uuid.uuid4(), user_id=buyer_user_id, player_id=player_id, delta=quantity))

    db.flush()


def user_holdings_at(db: Session, user_id: uuid.UUID, player_ids: list[uuid.UUID], at: datetime) -> dict[uuid.UUID, int]:
    """One user's shares held at instant `at`, for many players at once ({player_id: qty}, only > 0).
    Same maths as holdings_at, in two queries instead of two per player."""
    if not player_ids:
        return {}
    current = {
        pid: qty
        for pid, qty in db.query(Position.player_id, Position.quantity)
        .filter(Position.user_id == user_id, Position.player_id.in_(player_ids))
        .all()
    }
    after = {
        pid: int(total or 0)
        for pid, total in db.query(ShareTransfer.player_id, func.sum(ShareTransfer.delta))
        .filter(ShareTransfer.user_id == user_id, ShareTransfer.player_id.in_(player_ids), ShareTransfer.occurred_at > at)
        .group_by(ShareTransfer.player_id)
        .all()
    }
    out: dict[uuid.UUID, int] = {}
    for pid in set(current) | set(after):
        qty = current.get(pid, 0) - after.get(pid, 0)
        if qty > 0:
            out[pid] = qty
    return out


def holdings_at(db: Session, player_id: uuid.UUID, at: datetime) -> dict[uuid.UUID, int]:
    """{user_id: shares held at instant `at`} for one player (only users who held > 0).

    = each user's current Position.quantity minus every ledger delta recorded after `at`."""
    current: dict[uuid.UUID, int] = {
        uid: qty
        for uid, qty in db.query(Position.user_id, Position.quantity).filter(Position.player_id == player_id).all()
    }
    after: dict[uuid.UUID, int] = {}
    for uid, total in (
        db.query(ShareTransfer.user_id, func.sum(ShareTransfer.delta))
        .filter(ShareTransfer.player_id == player_id, ShareTransfer.occurred_at > at)
        .group_by(ShareTransfer.user_id)
        .all()
    ):
        after[uid] = int(total or 0)
    result: dict[uuid.UUID, int] = {}
    for uid in set(current) | set(after):
        qty = current.get(uid, 0) - after.get(uid, 0)
        if qty > 0:
            result[uid] = qty
    return result
