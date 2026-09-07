"""
Quick Buy / Quick Sell pricing.

*** PLACEHOLDER FORMULA -- read this before trusting the numbers ***
The exact quick-buy/quick-sell formula was supposed to come out of the
simulation phase of the roadmap (Phase 1). That phase's output wasn't
available when this backend was built, so the formula below is a
standard, defensible default used by real market-maker systems, clearly
isolated in this one function so it can be swapped for the "real" formula
later without touching the order book, wallet, or API code.

How it works:
  1. A quick order is a market order: it sweeps the resting order book
     (both real user limit orders and bot-provided liquidity orders --
     see matching_engine.py) at whatever price is available, best first.
  2. If the book cannot fully fill the requested quantity (thin or empty
     book), the unfilled remainder is filled synthetically by a "house"
     liquidity account at a price that gets worse the larger the order is
     relative to `synthetic_liquidity_depth` -- i.e. market impact /
     slippage. This guarantees quick orders always fill (no user is ever
     stuck unable to trade), while still penalizing large orders relative
     to a thin market, same as a real illiquid stock.

     synthetic_price(buy)  = reference_price * (1 + k * remaining/depth)
     synthetic_price(sell) = reference_price * (1 - k * remaining/depth)

     where:
       reference_price             = book mid-price, or last trade price,
                                      or an explicit fallback if the book
                                      has literally never traded
       k (market_impact_coefficient) = configurable, default 0.15
       depth (synthetic_liquidity_depth) = configurable per player,
                                      default: max(1% of shares
                                      outstanding, 100 shares) -- see
                                      DEFAULT_SYNTHETIC_DEPTH_FRACTION below

Sell-side synthetic price is floored at 0.01 so it can never go to zero or
negative.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from app.engine.matching_engine import OrderBook
from app.engine.types import Fill, Side

DEFAULT_MARKET_IMPACT_COEFFICIENT = Decimal("0.15")
DEFAULT_SYNTHETIC_DEPTH_FRACTION = Decimal("0.01")  # 1% of shares outstanding
DEFAULT_MIN_SYNTHETIC_DEPTH = Decimal("100")
MIN_PRICE = Decimal("0.01")

SYSTEM_LIQUIDITY_MAKER_ID = "SYSTEM_LIQUIDITY"


@dataclass
class QuickExecutionResult:
    fills: list[Fill] = field(default_factory=list)
    book_filled_quantity: Decimal = Decimal("0")
    synthetic_filled_quantity: Decimal = Decimal("0")
    unfilled_quantity: Decimal = Decimal("0")

    @property
    def total_filled_quantity(self) -> Decimal:
        return self.book_filled_quantity + self.synthetic_filled_quantity

    @property
    def vwap(self) -> Optional[Decimal]:
        filled = self.total_filled_quantity
        if filled == 0:
            return None
        notional = sum((f.price * f.quantity for f in self.fills), Decimal("0"))
        return notional / filled


def default_synthetic_depth(shares_outstanding: Decimal) -> Decimal:
    return max(shares_outstanding * DEFAULT_SYNTHETIC_DEPTH_FRACTION, DEFAULT_MIN_SYNTHETIC_DEPTH)


def estimate_quick_order_cost(
    book: OrderBook,
    side: Side,
    quantity: Decimal,
    shares_outstanding: Decimal,
    fallback_reference_price: Optional[Decimal] = None,
    market_impact_coefficient: Decimal = DEFAULT_MARKET_IMPACT_COEFFICIENT,
    synthetic_liquidity_depth: Optional[Decimal] = None,
    max_synthetic_quantity: Optional[Decimal] = None,
) -> Optional[Decimal]:
    """
    Non-mutating estimate of the total notional cost (BUY) or proceeds
    (SELL) of a quick order, computed by walking `book.depth()` snapshots
    instead of actually consuming the book. Used to pre-check a buyer has
    enough available cash *before* calling the mutating
    `execute_quick_order`, without side effects.

    Callers must hold the per-player book lock (see book_registry.py) for
    the entire time between calling this and calling `execute_quick_order`,
    so nothing else can change the book in between -- under that lock, this
    estimate and the real execution are guaranteed to agree exactly.

    `max_synthetic_quantity`, when given, caps how much of the order can
    be filled by the synthetic (House) leg after the real book is
    exhausted -- this MUST be the House's actual remaining share
    inventory for this player on a BUY order (there is no equivalent cap
    on a SELL order, since the House selling cash back to a seller is
    only constrained by its cash balance, checked elsewhere). Without
    this cap, a BUY quick order could synthesize a fill for more shares
    than the House actually owns, which the database's own conservation
    constraint on `positions.quantity` will then correctly reject -- but
    as a raw, unhandled integrity error deep in settlement instead of a
    clean "not enough liquidity" response. See execute_quick_order below
    for the matching guard on the mutating side.

    Returns None if there isn't enough information to price the order at
    all (empty book AND no fallback reference price), OR if there isn't
    enough real+synthetic supply to fill it at all (remaining demand
    would exceed `max_synthetic_quantity`).
    """
    if quantity <= 0:
        raise ValueError("quantity must be positive")

    depth = synthetic_liquidity_depth or default_synthetic_depth(shares_outstanding)
    opposite_side = Side.SELL if side == Side.BUY else Side.BUY
    levels = book.depth(opposite_side, max_levels=10_000)

    remaining = quantity
    total_notional = Decimal("0")
    for price, level_qty in levels:
        if remaining <= 0:
            break
        take = min(remaining, level_qty)
        total_notional += take * price
        remaining -= take

    if remaining > 0:
        if max_synthetic_quantity is not None and remaining > max_synthetic_quantity:
            return None
        reference_price = book.mid_price() or fallback_reference_price
        if reference_price is None:
            return None
        impact_ratio = remaining / depth
        if side == Side.BUY:
            synthetic_price = reference_price * (Decimal("1") + market_impact_coefficient * impact_ratio)
        else:
            synthetic_price = reference_price * (Decimal("1") - market_impact_coefficient * impact_ratio)
            synthetic_price = max(synthetic_price, MIN_PRICE)
        total_notional += remaining * synthetic_price

    return total_notional


def execute_quick_order(
    book: OrderBook,
    order_id: str,
    side: Side,
    quantity: Decimal,
    shares_outstanding: Decimal,
    fallback_reference_price: Optional[Decimal] = None,
    market_impact_coefficient: Decimal = DEFAULT_MARKET_IMPACT_COEFFICIENT,
    synthetic_liquidity_depth: Optional[Decimal] = None,
    max_synthetic_quantity: Optional[Decimal] = None,
) -> QuickExecutionResult:
    """
    Execute a quick buy/sell of `quantity` shares against `book`, falling
    back to synthetic house liquidity for whatever the book can't fill.

    `fallback_reference_price` must be supplied by the caller (typically
    the player's last known/IPO price) for the edge case where the book
    has never traded and has no resting orders at all.

    `max_synthetic_quantity` -- see estimate_quick_order_cost's docstring
    for the full rationale. If the amount left to synthesize after the
    real book is exhausted would exceed this cap, NONE of it is
    synthesized (this function does not partially honor a quick order --
    see order_service.place_quick_order, which rejects the whole order
    if anything is left unfilled).
    """
    if quantity <= 0:
        raise ValueError("quantity must be positive")

    depth = synthetic_liquidity_depth or default_synthetic_depth(shares_outstanding)

    # Capture the reference price BEFORE mutating the book. This must
    # happen first so that `estimate_quick_order_cost` (which never
    # mutates the book) and this function always agree exactly on the
    # synthetic leg's price -- see book_registry.py for why that
    # agreement is a safety-critical invariant, not just a nice-to-have.
    pre_trade_reference_price = book.mid_price() or fallback_reference_price

    match = book.add_quick_order(order_id=order_id, side=side, quantity=quantity)

    result = QuickExecutionResult()
    result.fills.extend(match.fills)
    result.book_filled_quantity = match.filled_quantity

    remaining = match.remaining_quantity
    if remaining > 0:
        if max_synthetic_quantity is not None and remaining > max_synthetic_quantity:
            # Not enough real House inventory left to cover the rest of
            # this order synthetically -- leave it entirely unfilled
            # rather than draining the House's position below zero.
            result.unfilled_quantity = remaining
            return result

        reference_price = pre_trade_reference_price
        if reference_price is None:
            # Nothing has ever traded and no fallback was given -- we
            # cannot invent a price out of thin air. Caller must handle
            # `unfilled_quantity > 0` (e.g. reject the order, or require
            # an admin-set IPO price before a player can be traded).
            result.unfilled_quantity = remaining
            return result

        impact_ratio = remaining / depth
        if side == Side.BUY:
            synthetic_price = reference_price * (Decimal("1") + market_impact_coefficient * impact_ratio)
        else:
            synthetic_price = reference_price * (Decimal("1") - market_impact_coefficient * impact_ratio)
            synthetic_price = max(synthetic_price, MIN_PRICE)

        result.fills.append(
            Fill(
                price=synthetic_price,
                quantity=remaining,
                maker_order_id=SYSTEM_LIQUIDITY_MAKER_ID,
                taker_order_id=order_id,
                maker_is_bot=True,
                taker_is_bot=False,
            )
        )
        result.synthetic_filled_quantity = remaining
        book.last_trade_price = synthetic_price

    return result
