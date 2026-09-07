"""
Shared plain-data types used across the pure engines.

These are intentionally simple dataclasses -- no ORM, no validation
framework. The `app/services/` layer builds these from database rows and
reads them back after calling an engine function.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Optional


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderKind(str, Enum):
    LIMIT = "limit"
    QUICK = "quick"  # "market" order: fill immediately at best available price(s)


@dataclass
class RestingOrder:
    """
    One resting (unfilled or partially filled) limit order sitting on the
    book. `order_id` is opaque to the engine -- the service layer maps it
    back to a real Order row (or a synthetic bot id).
    """
    order_id: str
    side: Side
    price: Decimal
    quantity: Decimal          # original quantity
    remaining: Decimal         # quantity still open
    sequence: int              # insertion order, used for FIFO tie-break
    is_bot: bool = False


@dataclass
class Fill:
    """One execution resulting from matching two orders (or a quick order
    against resting liquidity)."""
    price: Decimal
    quantity: Decimal
    maker_order_id: str
    taker_order_id: str
    maker_is_bot: bool = False
    taker_is_bot: bool = False


@dataclass
class MatchResult:
    fills: list[Fill] = field(default_factory=list)
    remaining_quantity: Decimal = Decimal("0")

    @property
    def filled_quantity(self) -> Decimal:
        return sum((f.quantity for f in self.fills), Decimal("0"))

    @property
    def vwap(self) -> Optional[Decimal]:
        filled = self.filled_quantity
        if filled == 0:
            return None
        notional = sum((f.price * f.quantity for f in self.fills), Decimal("0"))
        return notional / filled
