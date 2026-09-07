"""
Position (share holding) operations -- the share-side mirror of
wallet_service.py's cash operations. Same convention: functions here
`db.flush()` but never `db.commit()`.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.player import Position
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

    db.flush()
