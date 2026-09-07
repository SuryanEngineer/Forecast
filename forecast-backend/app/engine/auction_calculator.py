"""
Player-share IPO auction allocation math -- pure, no database, no I/O.
See app/services/auction_service.py for how this plugs into real bids,
wallet holds, and share positions.

Uses exact largest-remainder apportionment: every bidder's precise
fractional share entitlement is floored, then the small remainder
(guaranteed to be between 0 and len(bids)-1 shares) is handed out one
share at a time to whoever had the largest fractional remainder,
breaking ties by user_id for determinism. This guarantees total shares
allocated always sums to exactly `shares_available` -- never more, never
less. The same method (and the same bug it fixes -- independent
per-bidder rounding silently over- or under-allocating the total) was
found and proven correct the hard way in the forecast_sim Python economy
simulator this backend's economics are meant to match.

Money-side guarantee: no bidder is ever charged more than the
`bid_amount` they explicitly committed. A bidder who wins one of the
"remainder" shares has an exact proportional cost that can nominally
exceed their own bid by a fraction of one share's price (since they're
being given MORE than their exact floor entitlement); when that would
happen, the charge is capped at their bid_amount instead, and the
platform simply collects a little less for that player's auction rather
than ever overdrawing a bidder who never agreed to pay more. This is a
deliberate trade-off: share-count conservation is exact (that's the
property the simulation validated and is safety-critical -- it's what
"how many shares of this player exist" means), while total-cash-collected
is allowed a small, bounded shortfall in the bidders' favor instead of
ever violating someone's wallet balance.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

MONEY_PLACES = Decimal("0.0001")


@dataclass(frozen=True)
class BidInput:
    bid_id: str
    user_id: str
    bid_amount: Decimal


@dataclass(frozen=True)
class BidAllocation:
    bid_id: str
    user_id: str
    shares_won: int
    amount_charged: Decimal    # always <= this bid's bid_amount
    amount_released: Decimal   # bid_amount - amount_charged, i.e. what goes back to available balance


@dataclass(frozen=True)
class AuctionSettlement:
    clearing_price: Decimal
    allocations: list[BidAllocation]


def settle_player_auction(bids: list[BidInput], shares_available: int) -> AuctionSettlement:
    """Allocate `shares_available` shares across `bids` proportional to
    each bid's dollar amount. Raises ValueError if there's nothing
    meaningful to allocate (empty bids, non-positive shares, or
    non-positive total demand) -- the caller (auction_service.py) decides
    what "nothing to allocate" means for wallets/positions (releasing
    every hold in full), since that's a service-layer decision, not math."""
    if shares_available <= 0:
        raise ValueError("shares_available must be positive")
    if not bids:
        raise ValueError("bids must not be empty")

    total_bids = sum((b.bid_amount for b in bids), Decimal("0"))
    if total_bids <= 0:
        raise ValueError("total_bids must be positive")

    clearing_price = (total_bids / shares_available).quantize(MONEY_PLACES, rounding=ROUND_DOWN)
    if clearing_price <= 0:
        clearing_price = MONEY_PLACES  # smallest representable positive price -- guards a pathological edge case

    entitlements: list[tuple[BidInput, int, Decimal]] = []  # (bid, floor_shares, fractional_remainder)
    floor_sum = 0
    for bid in bids:
        exact = (bid.bid_amount / total_bids) * shares_available
        floor_shares = int(exact.to_integral_value(rounding=ROUND_DOWN))
        remainder = exact - floor_shares
        entitlements.append((bid, floor_shares, remainder))
        floor_sum += floor_shares

    leftover = shares_available - floor_sum
    entitlements.sort(key=lambda row: (-row[2], row[0].user_id))

    shares_by_bid_id: dict[str, int] = {bid.bid_id: floor_shares for bid, floor_shares, _ in entitlements}
    for i in range(max(leftover, 0)):
        bid = entitlements[i % len(entitlements)][0]
        shares_by_bid_id[bid.bid_id] += 1

    allocations: list[BidAllocation] = []
    for bid in bids:
        shares_won = shares_by_bid_id.get(bid.bid_id, 0)
        if shares_won <= 0:
            allocations.append(BidAllocation(bid.bid_id, bid.user_id, 0, Decimal("0"), bid.bid_amount))
            continue
        exact_charge = (Decimal(shares_won) * clearing_price).quantize(MONEY_PLACES, rounding=ROUND_DOWN)
        amount_charged = min(exact_charge, bid.bid_amount)
        allocations.append(
            BidAllocation(bid.bid_id, bid.user_id, shares_won, amount_charged, bid.bid_amount - amount_charged)
        )

    total_shares_allocated = sum(a.shares_won for a in allocations)
    if total_shares_allocated != shares_available:
        # Should be mathematically impossible -- guarded explicitly
        # because share conservation is the one property this whole
        # module exists to guarantee.
        raise AssertionError(
            f"share conservation violated: allocated {total_shares_allocated}, expected {shares_available}"
        )

    return AuctionSettlement(clearing_price=clearing_price, allocations=allocations)
