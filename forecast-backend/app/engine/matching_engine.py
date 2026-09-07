"""
Price-time priority limit order book.

This is a standard exchange-style matching engine: two heaps (bids sorted
highest-price-first, asks sorted lowest-price-first, ties broken by arrival
order / FIFO). It has no idea what a "player" or a "user" is -- it only
knows about opaque order ids, sides, prices and quantities. One OrderBook
instance exists per tradeable player-share in the service layer.

Both real user limit orders AND bot-provided liquidity orders (see roadmap:
"bots providing liquidity") are added through the exact same
`add_limit_order` call with `is_bot=True` -- from the matching engine's
point of view they are indistinguishable, which is what makes "quick
buy/sell" (see quick_trade_pricing.py) work: a quick order simply sweeps
whatever is resting on the book, bot or human.

Money is always `decimal.Decimal`. Never use float for price/quantity.
"""
from __future__ import annotations

import heapq
import itertools
from decimal import Decimal
from typing import Optional

from app.engine.types import Fill, MatchResult, RestingOrder, Side


class OrderBook:
    def __init__(self, player_id: str):
        self.player_id = player_id
        # heap entries: (sort_key, sequence, order_id)
        # bids: sort_key = -price  (so highest price pops first)
        # asks: sort_key =  price  (so lowest price pops first)
        self._bid_heap: list[tuple[Decimal, int, str]] = []
        self._ask_heap: list[tuple[Decimal, int, str]] = []
        self._orders: dict[str, RestingOrder] = {}
        self._cancelled: set[str] = set()
        self._seq = itertools.count()
        self.last_trade_price: Optional[Decimal] = None

    # ------------------------------------------------------------------ #
    # Book state
    # ------------------------------------------------------------------ #

    def _clean_bid_top(self) -> None:
        while self._bid_heap:
            _, _, oid = self._bid_heap[0]
            order = self._orders.get(oid)
            if oid in self._cancelled or order is None or order.remaining <= 0:
                heapq.heappop(self._bid_heap)
                continue
            return

    def _clean_ask_top(self) -> None:
        while self._ask_heap:
            _, _, oid = self._ask_heap[0]
            order = self._orders.get(oid)
            if oid in self._cancelled or order is None or order.remaining <= 0:
                heapq.heappop(self._ask_heap)
                continue
            return

    @property
    def best_bid(self) -> Optional[RestingOrder]:
        self._clean_bid_top()
        if not self._bid_heap:
            return None
        return self._orders[self._bid_heap[0][2]]

    @property
    def best_ask(self) -> Optional[RestingOrder]:
        self._clean_ask_top()
        if not self._ask_heap:
            return None
        return self._orders[self._ask_heap[0][2]]

    def mid_price(self) -> Optional[Decimal]:
        bid, ask = self.best_bid, self.best_ask
        if bid and ask:
            return (bid.price + ask.price) / 2
        if bid:
            return bid.price
        if ask:
            return ask.price
        return self.last_trade_price

    def depth(self, side: Side, max_levels: int = 10) -> list[tuple[Decimal, Decimal]]:
        """Aggregated (price, total_remaining_quantity) levels, best first."""
        heap = self._bid_heap if side == Side.BUY else self._ask_heap
        seen: dict[Decimal, Decimal] = {}
        order_ids_in_level_order: list[Decimal] = []
        for _, _, oid in sorted(heap):
            order = self._orders.get(oid)
            if order is None or oid in self._cancelled or order.remaining <= 0:
                continue
            if order.price not in seen:
                order_ids_in_level_order.append(order.price)
            seen[order.price] = seen.get(order.price, Decimal("0")) + order.remaining
        prices = sorted(seen.keys(), reverse=(side == Side.BUY))
        return [(p, seen[p]) for p in prices[:max_levels]]

    # ------------------------------------------------------------------ #
    # Order entry
    # ------------------------------------------------------------------ #

    def add_limit_order(
        self, order_id: str, side: Side, price: Decimal, quantity: Decimal, is_bot: bool = False
    ) -> MatchResult:
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        if price <= 0:
            raise ValueError("price must be positive")

        order = RestingOrder(
            order_id=order_id,
            side=side,
            price=price,
            quantity=quantity,
            remaining=quantity,
            sequence=next(self._seq),
            is_bot=is_bot,
        )
        self._orders[order_id] = order

        result = MatchResult()
        self._match(order, result, limit_price=price)

        if order.remaining > 0:
            self._rest(order)
        result.remaining_quantity = order.remaining
        return result

    def add_quick_order(self, order_id: str, side: Side, quantity: Decimal, is_bot: bool = False) -> MatchResult:
        """
        A "quick buy" / "quick sell" is a market order: it accepts any
        available price and sweeps the book until `quantity` is filled or
        the book runs out of liquidity on that side. It never rests --
        whatever isn't filled is returned as `remaining_quantity` so the
        caller (quick_trade_pricing.py) can apply the synthetic fallback
        formula to the unfilled remainder.
        """
        if quantity <= 0:
            raise ValueError("quantity must be positive")

        order = RestingOrder(
            order_id=order_id,
            side=side,
            price=Decimal("0") if side == Side.BUY else Decimal("Infinity"),
            quantity=quantity,
            remaining=quantity,
            sequence=next(self._seq),
            is_bot=is_bot,
        )
        # Quick orders never rest, so we don't store them in self._orders.
        result = MatchResult()
        self._match(order, result, limit_price=None)
        result.remaining_quantity = order.remaining
        return result

    def cancel(self, order_id: str) -> bool:
        order = self._orders.get(order_id)
        if order is None or order.remaining <= 0 or order_id in self._cancelled:
            return False
        self._cancelled.add(order_id)
        return True

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _rest(self, order: RestingOrder) -> None:
        if order.side == Side.BUY:
            heapq.heappush(self._bid_heap, (-order.price, order.sequence, order.order_id))
        else:
            heapq.heappush(self._ask_heap, (order.price, order.sequence, order.order_id))

    def _match(self, taker: RestingOrder, result: MatchResult, limit_price: Optional[Decimal]) -> None:
        """Match `taker` against the opposite side of the book in place,
        mutating `taker.remaining` and appending Fills to `result`."""
        opposite_best = self.best_ask if taker.side == Side.BUY else self.best_bid

        while taker.remaining > 0 and opposite_best is not None:
            crosses = (
                limit_price is None
                or (taker.side == Side.BUY and limit_price >= opposite_best.price)
                or (taker.side == Side.SELL and limit_price <= opposite_best.price)
            )
            if not crosses:
                break

            trade_qty = min(taker.remaining, opposite_best.remaining)
            trade_price = opposite_best.price  # resting order sets the price (maker's price)

            opposite_best.remaining -= trade_qty
            taker.remaining -= trade_qty
            self.last_trade_price = trade_price

            if taker.side == Side.BUY:
                fill = Fill(
                    price=trade_price,
                    quantity=trade_qty,
                    maker_order_id=opposite_best.order_id,
                    taker_order_id=taker.order_id,
                    maker_is_bot=opposite_best.is_bot,
                    taker_is_bot=taker.is_bot,
                )
            else:
                fill = Fill(
                    price=trade_price,
                    quantity=trade_qty,
                    maker_order_id=opposite_best.order_id,
                    taker_order_id=taker.order_id,
                    maker_is_bot=opposite_best.is_bot,
                    taker_is_bot=taker.is_bot,
                )
            result.fills.append(fill)

            if opposite_best.remaining <= 0:
                opposite_best = self.best_ask if taker.side == Side.BUY else self.best_bid
            else:
                # Still liquidity at this price/order, but it's now smaller;
                # best_bid/best_ask recompute from heap top, which is still
                # correct since we mutated the same object referenced there.
                opposite_best = self.best_ask if taker.side == Side.BUY else self.best_bid
