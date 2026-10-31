"""
Ties the resting order book into the price a stock is LISTED at.

The last trade alone can go stale: if people are posting bids above it (or asks below it) the market has already moved
and the listed price should say so. Rule:

    listed price = last trade price, pulled up to the best bid if that is higher, or down to the best ask if that is lower

An uncrossed book always has bid < ask, so the listed price is the last trade when it sits inside the spread (the normal
case) and otherwise snaps to the nearest side of the spread -- "people will pay more than the last price -> price rises;
people will sell for less -> price falls".

Safeguards so a lone order can't drag the price around:
  * only orders worth at least MIN_NOTIONAL dollars of remaining size count (a 1-share bid can't move anything);
  * the book can move the price at most MAX_PULL (6%) away from the last trade; bigger moves need real trades.
Pure read-side: nothing here writes.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.order import Order, OrderKind, OrderSide, OrderStatus

MIN_NOTIONAL = Decimal("100")
MAX_PULL = Decimal("0.06")

_OPEN = [OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED]


def _remaining():
    return Order.quantity - Order.filled_quantity


def bulk_best_quotes(db: Session, player_ids: list[uuid.UUID] | None = None) -> dict[uuid.UUID, tuple[Decimal | None, Decimal | None]]:
    """{player_id: (best_bid, best_ask)} over significant resting limit orders, in two grouped queries. `player_ids=None`
    covers every player with open orders (used by the bots)."""
    out: dict[uuid.UUID, list[Decimal | None]] = {}
    if player_ids is not None and not player_ids:
        return {}
    for side, agg, idx in ((OrderSide.BUY, func.max, 0), (OrderSide.SELL, func.min, 1)):
        q = db.query(Order.player_id, agg(Order.limit_price)).filter(
            Order.status.in_(_OPEN),
            Order.order_kind == OrderKind.LIMIT,
            Order.side == side,
            Order.limit_price.isnot(None),
            _remaining() > 0,
            _remaining() * Order.limit_price >= MIN_NOTIONAL,
        )
        if player_ids is not None:
            q = q.filter(Order.player_id.in_(player_ids))
        for pid, price in q.group_by(Order.player_id).all():
            out.setdefault(pid, [None, None])[idx] = price
    return {pid: (v[0], v[1]) for pid, v in out.items()}


def effective_price(last: Decimal, best_bid: Decimal | None, best_ask: Decimal | None) -> Decimal:
    """The listed price: the last trade clamped into [best bid, best ask], moved at most MAX_PULL from the last trade."""
    if last is None or last <= 0:
        return last
    price = last
    if best_bid is not None and best_bid > price:
        price = min(best_bid, last * (Decimal("1") + MAX_PULL))
    elif best_ask is not None and best_ask < price:
        price = max(best_ask, last * (Decimal("1") - MAX_PULL))
    return price.quantize(Decimal("0.01"))


def apply_book(db: Session, last_prices: dict[uuid.UUID, Decimal]) -> dict[uuid.UUID, Decimal]:
    """Listed price for each player in `last_prices` ({player_id: last trade price})."""
    quotes = bulk_best_quotes(db, list(last_prices.keys()))
    return {pid: effective_price(px, *quotes.get(pid, (None, None))) for pid, px in last_prices.items()}


def book_levels(db: Session, player_id: uuid.UUID, depth: int = 10) -> dict:
    """Aggregated order book for one player: bids (best first) and asks (best first) as {price, quantity, orders}."""
    rows = (
        db.query(Order.side, Order.limit_price, func.sum(_remaining()), func.count(Order.id))
        .filter(
            Order.player_id == player_id,
            Order.status.in_(_OPEN),
            Order.order_kind == OrderKind.LIMIT,
            Order.limit_price.isnot(None),
            _remaining() > 0,
        )
        .group_by(Order.side, Order.limit_price)
        .all()
    )
    bids = sorted(([p, int(q), int(n)] for s, p, q, n in rows if s == OrderSide.BUY), key=lambda r: r[0], reverse=True)[:depth]
    asks = sorted(([p, int(q), int(n)] for s, p, q, n in rows if s == OrderSide.SELL), key=lambda r: r[0])[:depth]
    shape = lambda rs: [{"price": p, "quantity": q, "orders": n} for p, q, n in rs]
    return {"bids": shape(bids), "asks": shape(asks)}
