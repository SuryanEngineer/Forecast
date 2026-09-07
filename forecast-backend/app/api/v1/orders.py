from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.order import Order, Trade
from app.models.user import User
from app.schemas.order import LimitOrderRequest, OrderResponse, QuickOrderRequest, TradeResponse
from app.services import order_service
from app.services.exceptions import ServiceError

router = APIRouter(prefix="/orders", tags=["orders"])


def _to_http_error(exc: ServiceError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/limit", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
def place_limit_order(payload: LimitOrderRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> OrderResponse:
    try:
        order = order_service.place_limit_order(db, user.id, payload.player_id, payload.side, payload.price, payload.quantity)
        db.commit()
    except ServiceError as exc:
        db.rollback()
        raise _to_http_error(exc)
    return order


@router.post("/quick", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
def place_quick_order(payload: QuickOrderRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> OrderResponse:
    """'Quick buy' / 'quick sell' -- fills immediately at the best
    available price (sweeping the order book, falling back to synthetic
    House liquidity for the remainder). See
    app/engine/quick_trade_pricing.py for the pricing formula, which is a
    documented placeholder pending the roadmap's simulation output."""
    try:
        order = order_service.place_quick_order(db, user.id, payload.player_id, payload.side, payload.quantity)
        db.commit()
    except ServiceError as exc:
        db.rollback()
        raise _to_http_error(exc)
    return order


@router.post("/{order_id}/cancel", response_model=OrderResponse)
def cancel_order(order_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> OrderResponse:
    try:
        order = order_service.cancel_order(db, user.id, order_id)
        db.commit()
    except ServiceError as exc:
        db.rollback()
        raise _to_http_error(exc)
    return order


@router.get("/me", response_model=list[OrderResponse])
def list_my_orders(player_id: uuid.UUID | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[OrderResponse]:
    query = db.query(Order).filter(Order.user_id == user.id)
    if player_id is not None:
        query = query.filter(Order.player_id == player_id)
    return query.order_by(Order.created_at.desc()).limit(200).all()


@router.get("/trades/{player_id}", response_model=list[TradeResponse])
def list_recent_trades(player_id: uuid.UUID, limit: int = 100, db: Session = Depends(get_db)) -> list[TradeResponse]:
    return (
        db.query(Trade)
        .filter(Trade.player_id == player_id)
        .order_by(Trade.executed_at.desc())
        .limit(min(limit, 500))
        .all()
    )
