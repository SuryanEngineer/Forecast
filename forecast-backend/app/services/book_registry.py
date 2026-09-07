"""
Process-wide in-memory registry of live OrderBook instances, one per
player.

*** IMPORTANT SCALING NOTE ***
This keeps order-book state in this process's memory, guarded by a Python
lock per player. That's correct and simple for a single-process v1 (one
FastAPI worker). The roadmap calls for "Redis for order-book state and
pub/sub" specifically so that (a) multiple API processes/machines share
one consistent book and (b) a restart doesn't lose in-flight book state
mid-second. Rebuilding from the database on every startup (which this
module does) covers correctness for a single process; moving the actual
`OrderBook` contents into Redis (or routing all order entry through one
dedicated matching-engine process/queue) is the follow-up work needed
before running more than one API worker process. Flagged here so it
isn't forgotten -- see README_SETUP.md, "Scaling beyond a single
process."
"""
from __future__ import annotations

import threading
import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from app.engine.matching_engine import OrderBook
from app.engine.types import Side
from app.models.order import Order, OrderKind, OrderSide, OrderStatus

_books: dict[str, OrderBook] = {}
_book_locks: dict[str, threading.Lock] = {}
_registry_lock = threading.Lock()


def _player_key(player_id: uuid.UUID) -> str:
    return str(player_id)


def get_player_lock(player_id: uuid.UUID) -> threading.Lock:
    key = _player_key(player_id)
    with _registry_lock:
        if key not in _book_locks:
            _book_locks[key] = threading.Lock()
        return _book_locks[key]


def get_book(db: Session, player_id: uuid.UUID) -> OrderBook:
    """Return the cached OrderBook for this player, building it from every
    OPEN/PARTIALLY_FILLED limit order in the database if it isn't cached
    yet. Callers MUST hold `get_player_lock(player_id)` before calling
    this and while doing anything with the returned book."""
    key = _player_key(player_id)
    if key in _books:
        return _books[key]

    book = OrderBook(player_id=key)
    open_orders = (
        db.query(Order)
        .filter(
            Order.player_id == player_id,
            Order.order_kind == OrderKind.LIMIT,
            Order.status.in_([OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED]),
        )
        .order_by(Order.created_at.asc())
        .all()
    )
    for order in open_orders:
        remaining = Decimal(order.quantity - order.filled_quantity)
        if remaining <= 0:
            continue
        side = Side.BUY if order.side == OrderSide.BUY else Side.SELL
        book.add_limit_order(
            order_id=str(order.id), side=side, price=order.limit_price, quantity=remaining, is_bot=order.is_bot
        )
    _books[key] = book
    return book


def reset_book_cache() -> None:
    """Used by tests / the smoke-test script to force a clean rebuild."""
    _books.clear()
