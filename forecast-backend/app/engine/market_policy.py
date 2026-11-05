"""
Pure pricing policy: what a price MEANS in this market. No database, no I/O -- every rule here is a small function so it
can be tested on its own and reused identically by order settlement, the market screens, net worth and the bots.

THE IDEA
--------
A stock has three different "prices", and mixing them up is what made the old numbers manipulable:

  1. REFERENCE PRICE (R) -- the market's running opinion. Every trade nudges it toward the trade price BY AN AMOUNT
     PROPORTIONAL TO ITS SIZE (a 1-share trade barely moves it; a trade the size of the House's depth moves it fully),
     it is re-set after a tournament result (rerate_service), and it can never leave a BAND around the stock's
     dividend-based fair value (default 0.5x - 2.0x). The House quotes around R.

  2. LISTED PRICE -- what the market screens show: the midpoint of the best price you could BUY at and the best price
     you could SELL at for a single share. The House always stands ready at R, so real orders only change the listed
     price when they are better than the House's quote; the pull is capped (MAX_PULL).

  3. HOLDING VALUE -- what your whole position is worth is what a quick-sell of ALL of it would pay right now: real
     resting bids first (never valued above R), then the House for whatever is left, at the House's size-dependent
     price. Big positions are worth less per share than small ones, exactly as in a real market, and a trade at a silly
     price cannot lift anyone's portfolio because nothing here looks at "the last trade".

Everything uses Decimal and returns Decimal.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional, Sequence

D = Decimal
BAND_LOW_DEFAULT = D("0.5")
BAND_HIGH_DEFAULT = D("2.0")
MAX_PULL = D("0.06")            # real orders may move the LISTED price at most this far from the reference
MIN_PRICE = D("0.50")     # no stock may trade below this, so nobody can corner the penny stocks
CENT = D("0.01")


# --- launch calibration --------------------------------------------------------------------------------------------


def solve_target_yield(
    income_per_share: Sequence[float],
    shares: Sequence[int],
    market_value: float,
    fair_min: float = 1.0,
    fair_max: float = 5000.0,
) -> float:
    """The yield y at which every stock priced at fair = income/y (clamped to [fair_min, fair_max]) adds up to `market_value`.

    This is how the launch price LEVEL is chosen: pick the total value the market should start at (e.g. 1.5x the cash
    players will hold) and the yield falls out of it; each stock's share of that value is its share of expected dividends.
    The total is non-increasing in y, so a bisection finds it. Returns the closest reachable yield if the target is out of range.
    """
    inc = [float(x) for x in income_per_share]
    sh = [float(s) for s in shares]
    target = float(market_value)

    def total(y: float) -> float:
        return sum(min(fair_max, max(fair_min, i / y)) * s for i, s in zip(inc, sh))

    lo, hi = 0.001, 5.0
    if total(lo) <= target:
        return lo
    if total(hi) >= target:
        return hi
    for _ in range(100):
        mid = (lo + hi) / 2.0
        if total(mid) > target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


# --- fair-value band -----------------------------------------------------------------------------------------------


def band_limits(fair: Decimal, low: Decimal = BAND_LOW_DEFAULT, high: Decimal = BAND_HIGH_DEFAULT) -> tuple[Decimal, Decimal]:
    lo = max(MIN_PRICE, fair * low)
    hi = max(lo, fair * high)
    return lo, hi


def clamp_to_band(price: Decimal, fair: Optional[Decimal], low: Decimal = BAND_LOW_DEFAULT, high: Decimal = BAND_HIGH_DEFAULT) -> Decimal:
    """Keep a price inside [low x fair, high x fair]. No fair value known -> unchanged."""
    if fair is None or fair <= 0:
        return price
    lo, hi = band_limits(fair, low, high)
    return min(max(price, lo), hi)


def in_band(price: Decimal, fair: Optional[Decimal], low: Decimal = BAND_LOW_DEFAULT, high: Decimal = BAND_HIGH_DEFAULT) -> bool:
    if fair is None or fair <= 0:
        return True
    lo, hi = band_limits(fair, low, high)
    return lo <= price <= hi


# --- the House's size-dependent price (slippage) ---------------------------------------------------------------------


def house_impact(qty: Decimal, depth: Decimal, k: Decimal, max_impact: Decimal) -> Decimal:
    """Fraction the House moves its price for an order of `qty` shares: k x qty/depth, never more than max_impact."""
    if depth <= 0:
        return max_impact
    return min(k * (qty / depth), max_impact)


def house_buy_price(ref: Decimal, qty: Decimal, depth: Decimal, k: Decimal, max_impact: Decimal) -> Decimal:
    """Per-share price the House SELLS at (you buy)."""
    return ref * (D("1") + house_impact(qty, depth, k, max_impact))


def house_sell_price(ref: Decimal, qty: Decimal, depth: Decimal, k: Decimal, max_impact: Decimal) -> Decimal:
    """Per-share price the House BUYS at (you sell)."""
    return max(ref * (D("1") - house_impact(qty, depth, k, max_impact)), MIN_PRICE)


# When nobody is selling except the House, the House does not sit far above the people who want to buy: its ask is held
# to within this fraction of the best real bid. (Real sellers, when there are any, are always hit first.)
HOUSE_ASK_GAP = D("0.03")


def house_ask_reference(ref: Decimal, best_bid: Optional[Decimal], has_real_ask: bool) -> Decimal:
    """The reference the House prices its SELL side off. Normally the market reference, but with no real asks and a real
    bid standing, it drops toward that bid (best bid + HOUSE_ASK_GAP) so the House doesn't hold the price high above
    where buyers actually are."""
    if has_real_ask or best_bid is None or best_bid <= 0:
        return ref
    return max(MIN_PRICE, min(ref, best_bid * (D("1") + HOUSE_ASK_GAP)))


# --- reference price -------------------------------------------------------------------------------------------------


def reference_after_trade(
    ref: Decimal, trade_price: Decimal, qty: Decimal, damping_depth: Decimal,
    fair: Optional[Decimal] = None, low: Decimal = BAND_LOW_DEFAULT, high: Decimal = BAND_HIGH_DEFAULT,
) -> Decimal:
    """New reference after a trade: move toward the trade price by qty/damping_depth (at most all the way), then keep
    it inside the fair-value band. A 1-share trade at a silly price moves R by ~1/damping_depth of the gap."""
    alpha = D("1") if damping_depth <= 0 else min(D("1"), qty / damping_depth)
    moved = ref + alpha * (trade_price - ref)
    return max(MIN_PRICE, clamp_to_band(moved, fair, low, high))


def limit_drift(new: Decimal, anchor: Decimal, max_move: Decimal) -> Decimal:
    """Keep `new` within +/- max_move (a fraction) of `anchor`. Used to stop a quiet market drifting fast: trades may
    still happen at any price, but the REFERENCE only follows them this far per window."""
    if anchor <= 0 or max_move < 0:
        return new
    lo, hi = anchor * (D("1") - max_move), anchor * (D("1") + max_move)
    return max(lo, min(hi, new))


# --- listed price ------------------------------------------------------------------------------------------------------


def listed_price(ref: Decimal, best_bid: Optional[Decimal], best_ask: Optional[Decimal], max_pull: Decimal = MAX_PULL) -> Decimal:
    """Midpoint of the best buy and best sell price for one share. The House stands ready at `ref` on both sides, so a
    real bid only counts when it is ABOVE ref and a real ask only when it is BELOW it."""
    bid_eff = max(best_bid, ref) if best_bid is not None else ref
    ask_eff = min(best_ask, ref) if best_ask is not None else ref
    mid = (bid_eff + ask_eff) / 2
    mid = min(max(mid, ref * (D("1") - max_pull)), ref * (D("1") + max_pull))
    return max(MIN_PRICE, mid).quantize(CENT)


# --- holding value -----------------------------------------------------------------------------------------------------


def liquidation_value(
    qty: int, ref: Decimal, bid_levels: Sequence[tuple[Decimal, int]],
    depth: Decimal, k: Decimal, max_impact: Decimal,
) -> Decimal:
    """Proceeds of quick-selling `qty` shares right now: resting bids first, best price first (a bid is never counted
    above `ref`, so nobody can lift their own value by posting a high bid), then the House for what is left at its
    size-dependent price. `bid_levels` is [(price, quantity)] best first."""
    if qty <= 0:
        return D("0")
    remaining = qty
    total = D("0")
    for price, level_qty in bid_levels:
        if remaining <= 0:
            break
        take = min(remaining, level_qty)
        if take <= 0:
            continue
        total += D(take) * min(price, ref)
        remaining -= take
    if remaining > 0:
        total += D(remaining) * house_sell_price(ref, D(remaining), depth, k, max_impact)
    return total
