"""
Read-side prices and valuations, all built from app/engine/market_policy.py:

  * listed price  -- the last real trade, kept between the sell and buy prices below (what the screens headline);
  * buy / sell    -- the actual price of ONE share to buy / to sell right now;
  * holding value -- what quick-selling the WHOLE position would pay (real bids capped at the reference price, then the
                     House at its size-dependent price). Net worth, leaderboards, seasons and stats use this.

Nothing here writes. `Valuer` loads everything once (reference prices, fair prices, bid levels, quotes) so valuing every
player's holdings costs a handful of queries, not one per position.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import time

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.engine import market_policy as mp
from app.models.order import Order, OrderKind, OrderSide, OrderStatus
from app.models.player import Player, PriceSnapshot
from app.services import book_price_service, economic_params_service, fair_price_service, reference_service

_OPEN = [OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED]
ZERO = Decimal("0")

_LAST_TRADE_CACHE: dict = {"at": 0.0, "data": {}}
_LAST_TRADE_TTL = 30.0


def last_trade_prices(db: Session) -> dict[uuid.UUID, Decimal]:
    """{player: price of the most recent REAL trade} (real trades are the price points with volume > 0; the simulated history
    has volume 0, so after a reset a stock has no 'last trade' until someone really trades it). Cached for a few seconds."""
    now = time.monotonic()
    if _LAST_TRADE_CACHE["data"] is not None and now - _LAST_TRADE_CACHE["at"] < _LAST_TRADE_TTL and _LAST_TRADE_CACHE["at"]:
        return _LAST_TRADE_CACHE["data"]
    latest = (
        db.query(PriceSnapshot.player_id.label("pid"), func.max(PriceSnapshot.recorded_at).label("mx"))
        .filter(PriceSnapshot.volume > 0)
        .group_by(PriceSnapshot.player_id)
        .subquery()
    )
    rows = (
        db.query(PriceSnapshot.player_id, PriceSnapshot.price)
        .join(latest, and_(PriceSnapshot.player_id == latest.c.pid, PriceSnapshot.recorded_at == latest.c.mx))
        .filter(PriceSnapshot.volume > 0)
        .all()
    )
    data = {pid: Decimal(px) for pid, px in rows}
    _LAST_TRADE_CACHE["at"] = now
    _LAST_TRADE_CACHE["data"] = data
    return data


class Valuer:
    def __init__(self, db: Session, player_ids: list[uuid.UUID] | None = None):
        get = lambda key: economic_params_service.get_param(db, key)
        self.low, self.high = get("market.band_low"), get("market.band_high")
        self.k = get("quick_trade.market_impact_coefficient")
        self.max_impact = Decimal("0.25")  # quick_trade_pricing.MAX_SYNTHETIC_IMPACT
        depth_frac, depth_min = get("quick_trade.synthetic_depth_fraction"), get("quick_trade.synthetic_depth_min")
        q = db.query(Player.id, Player.total_shares_outstanding, Player.ipo_price)
        if player_ids is not None:
            q = q.filter(Player.id.in_(player_ids))
        rows = q.all()
        ids = [pid for pid, _s, _i in rows]
        fair = fair_price_service.fair_prices(db)
        raw_refs = reference_service.get_refs(db, ids)
        self.depth: dict[uuid.UUID, Decimal] = {}
        self.ref: dict[uuid.UUID, Decimal] = {}
        for pid, shares, ipo in rows:
            self.depth[pid] = max(Decimal(shares) * depth_frac, depth_min)
            self.ref[pid] = mp.clamp_to_band(raw_refs.get(pid, ipo), fair.get(pid), self.low, self.high)
        self.quotes = book_price_service.bulk_best_quotes(db, ids)
        self.last_trade = last_trade_prices(db)
        # resting bid levels per player, best price first: [(price, remaining quantity)]
        rem = Order.quantity - Order.filled_quantity
        bids: dict[uuid.UUID, list[tuple[Decimal, int]]] = {}
        bq = (
            db.query(Order.player_id, Order.limit_price, func.sum(rem))
            .filter(Order.status.in_(_OPEN), Order.order_kind == OrderKind.LIMIT, Order.side == OrderSide.BUY, Order.limit_price.isnot(None), rem > 0)
            .group_by(Order.player_id, Order.limit_price)
        )
        if player_ids is not None:
            bq = bq.filter(Order.player_id.in_(ids))
        for pid, price, qty in bq.all():
            bids.setdefault(pid, []).append((price, int(qty)))
        self.bids = {pid: sorted(levels, key=lambda r: r[0], reverse=True) for pid, levels in bids.items()}

    def reference(self, pid: uuid.UUID) -> Decimal:
        return self.ref.get(pid, ZERO)

    def listed(self, pid: uuid.UUID) -> Decimal:
        """The price shown for a stock: the LAST TRADE, kept between the Sell and Buy prices (above Buy -> Buy, below Sell ->
        Sell). With no real trade yet it is the reference price."""
        ref = self.ref.get(pid)
        if ref is None:
            return ZERO
        buy, sell = self.buy_sell(pid)
        lo, hi = min(buy, sell), max(buy, sell)
        last = self.last_trade.get(pid, ref)
        return min(max(last, lo), hi).quantize(Decimal("0.01"))

    def buy_sell(self, pid: uuid.UUID, qty: int = 1) -> tuple[Decimal, Decimal]:
        """Per-share price to BUY and to SELL `qty` shares right now (real best quote vs the House, whichever is better)."""
        ref = self.ref.get(pid)
        if ref is None:
            return ZERO, ZERO
        depth = self.depth[pid]
        bid, ask = self.quotes.get(pid, (None, None))
        best_bid = self.bids.get(pid, [(None, 0)])[0][0] if self.bids.get(pid) else None
        buy = mp.house_buy_price(mp.house_ask_reference(ref, best_bid, ask is not None), Decimal(qty), depth, self.k, self.max_impact)
        sell = mp.house_sell_price(ref, Decimal(qty), depth, self.k, self.max_impact)
        if ask is not None:
            buy = min(buy, ask)
        if bid is not None:
            sell = max(sell, min(bid, ref))
        return buy.quantize(Decimal("0.01")), sell.quantize(Decimal("0.01"))

    def value(self, pid: uuid.UUID, qty: int) -> Decimal:
        """What quick-selling `qty` shares would pay right now."""
        ref = self.ref.get(pid)
        if ref is None or qty <= 0:
            return ZERO
        return mp.liquidation_value(qty, ref, self.bids.get(pid, []), self.depth[pid], self.k, self.max_impact)

    def haircut(self, pid: uuid.UUID, qty: int) -> Decimal:
        """liquidation value / (qty x listed price): how much of the headline price a position this size really fetches."""
        listed = self.listed(pid)
        if qty <= 0 or listed <= 0:
            return Decimal("1")
        return self.value(pid, qty) / (listed * qty)


def listed_prices(db: Session, player_ids: list[uuid.UUID] | None = None) -> dict[uuid.UUID, Decimal]:
    v = Valuer(db, player_ids)
    return {pid: v.listed(pid) for pid in v.ref}


def sides(db: Session, player_ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[Decimal, Decimal]]:
    v = Valuer(db, player_ids)
    return {pid: v.buy_sell(pid) for pid in v.ref}
