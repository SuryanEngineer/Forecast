"""
Dividend calculation.

*** PLACEHOLDER FORMULA -- read this before trusting the numbers ***
Same caveat as quick_trade_pricing.py: the exact payout curve belongs in
the simulation phase of the roadmap. What's implemented here is a
standard, documented default:

  1. Per-player payout pool for a tournament:
       - If the admin entered an actual `prize_won` amount for that
         player's placement (the normal case -- most tournaments publish
         exact payouts per placement), that figure is used directly.
       - Otherwise, fall back to `DEFAULT_PLACEMENT_CURVE`, a standard
         top-heavy esports payout curve applied to the tournament's total
         prize pool, keyed by placement bracket.
     A platform fee (default 0%, configurable) is taken off the top
     before the remainder is distributed to shareholders -- this is the
     lever the roadmap's simulation would use as one of the "inflation"
     controls (fees drain currency from circulation).

  2. Per-share payout = (pool - fee) / shares_outstanding, distributed
     pro-rata to every shareholder's position *as of the moment the
     placement result is ingested* (the "record date" / "ex-dividend"
     snapshot -- taken by the service layer, not here). This engine only
     does the math once it's handed a fixed list of (user_id, quantity)
     holdings.

  3. Because per-share amounts rarely divide evenly, rounding is done with
     the "largest remainder" method so that the sum of all shareholder
     payouts plus the fee is always *exactly* equal to the pool amount --
     no money is created or destroyed by rounding.
"""
from __future__ import annotations

from decimal import ROUND_DOWN, Decimal
from typing import Optional

CENT = Decimal("0.01")

# Placement -> fraction of total tournament prize pool, standard top-heavy
# esports curve. Anything not listed (placements beyond what's covered)
# gets 0. This is only used when an admin hasn't entered an exact
# `prize_won` figure for that placement.
DEFAULT_PLACEMENT_CURVE: dict[int, Decimal] = {
    1: Decimal("0.20"),
    2: Decimal("0.13"),
    3: Decimal("0.10"),
    4: Decimal("0.08"),
    5: Decimal("0.06"),
    6: Decimal("0.06"),
    7: Decimal("0.04"),
    8: Decimal("0.04"),
    9: Decimal("0.025"),
    10: Decimal("0.025"),
    11: Decimal("0.025"),
    12: Decimal("0.025"),
}


# How gently the tail decays per placement past the end of the explicit
# curve -- close to 1 on purpose, so even the very back of a big lobby
# still gets a real (if tiny) sliver instead of the payout curve bottoming
# out to nothing a few placements past the explicit curve's end. At
# r=0.965, a placement 87 slots past the curve's end still earns roughly
# 4.5% of what the first tail placement does -- small, but a
# consistently-bottom-placing player is still worth owning if their share
# price is cheap enough for that trickle to matter.
_TAIL_DECAY_RATE = 0.965


def placement_payout_fraction(placement: int, max_placement: int, placement_curve: dict[int, Decimal]) -> Decimal:
    """What fraction of a tournament's pool a given placement earns, out
    of `max_placement` total placements available in this specific
    tournament (however many PlacementResult rows it actually has -- see
    dividend_service.create_payout_for_placement's caller).

    Previously, only whatever placements were explicitly listed in
    `placement_curve` (1-12 by default) got a nonzero payout -- everything
    past that got flat $0, no matter how big the lobby was, so a
    tournament's leaderboard only had real stakes for its top handful of
    finishers. Now, an explicit entry in `placement_curve` (including any
    admin-added ones beyond the default 12 -- see
    economic_params_service.set_placement_curve_entry) always wins; for
    everything else from there down to `max_placement`, the remaining
    budget (1 minus whatever the explicit entries already sum to) is split
    across the rest of the field via a smooth geometric decay, so every
    placement in a full field gets something and there's no placement past
    which a finish is worth literally nothing."""
    if placement in placement_curve:
        return placement_curve[placement]
    if placement > max_placement or not placement_curve:
        return Decimal("0")

    explicit_max = max(placement_curve.keys())
    explicit_total = sum(placement_curve.values(), Decimal("0"))
    tail_budget = Decimal("1") - explicit_total
    if placement <= explicit_max or tail_budget <= 0:
        return Decimal("0")

    tail_length = max_placement - explicit_max
    if tail_length <= 0:
        return Decimal("0")

    k = placement - explicit_max - 1  # 0-based offset into the tail
    r = _TAIL_DECAY_RATE
    sum_of_weights = (1 - r**tail_length) / (1 - r)
    weight = r**k
    return tail_budget * Decimal(str(weight / sum_of_weights))


def compute_player_pool(
    placement: int,
    prize_won: Optional[Decimal],
    tournament_prize_pool: Optional[Decimal],
    max_placement: int,
    placement_curve: dict[int, Decimal] = DEFAULT_PLACEMENT_CURVE,
) -> Decimal:
    """Amount of real-world prize money attributed to this player's
    placement, which becomes the dividend pool for their shareholders."""
    if prize_won is not None:
        return prize_won
    if tournament_prize_pool is None:
        return Decimal("0")
    fraction = placement_payout_fraction(placement, max_placement, placement_curve)
    return (tournament_prize_pool * fraction).quantize(CENT, rounding=ROUND_DOWN)


def compute_dividend_distribution(
    pool_amount: Decimal,
    shares_outstanding: Decimal,
    holders: list[tuple[str, Decimal]],
    platform_fee_pct: Decimal = Decimal("0"),
) -> tuple[Decimal, list[tuple[str, Decimal]], Decimal]:
    """
    Returns (per_share_amount, [(user_id, amount_paid), ...], fee_amount).

    `holders` is the full shareholder snapshot for this player at record
    date: every (user_id, quantity_held) pair with quantity_held > 0.
    Sum of quantities should equal `shares_outstanding` (the service layer
    is responsible for that invariant -- this function will still work
    correctly even if it doesn't, it just distributes pro-rata against
    whatever quantities it's given).
    """
    if shares_outstanding <= 0 or pool_amount <= 0 or not holders:
        return Decimal("0.00"), [(uid, Decimal("0.00")) for uid, _ in holders], Decimal("0.00")

    fee_amount = (pool_amount * platform_fee_pct).quantize(CENT, rounding=ROUND_DOWN)
    distributable = pool_amount - fee_amount
    per_share_amount = distributable / shares_outstanding

    # Largest-remainder rounding: give everyone the rounded-down cent
    # amount first, then hand out the leftover pennies (there will be at
    # most `len(holders) - 1` of them) to whoever had the largest
    # fractional remainder, breaking ties by user_id for determinism.
    raw_amounts: list[tuple[str, Decimal, Decimal]] = []  # (user_id, floor_amount, remainder)
    running_total = Decimal("0.00")
    for user_id, qty in holders:
        exact = qty * per_share_amount
        floor_amount = exact.quantize(CENT, rounding=ROUND_DOWN)
        remainder = exact - floor_amount
        raw_amounts.append((user_id, floor_amount, remainder))
        running_total += floor_amount

    leftover_cents = int(((distributable - running_total) / CENT).to_integral_value())

    raw_amounts.sort(key=lambda row: (-row[2], row[0]))
    payouts: dict[str, Decimal] = {uid: amt for uid, amt, _ in raw_amounts}
    for i in range(max(leftover_cents, 0)):
        uid = raw_amounts[i % len(raw_amounts)][0]
        payouts[uid] += CENT

    ordered_payouts = [(uid, payouts[uid]) for uid, _ in holders]
    return per_share_amount, ordered_payouts, fee_amount
