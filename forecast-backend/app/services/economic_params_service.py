"""
Central place every "how does the economy behave" knob is read from.

Every tunable value used by order_service.py, dividend_service.py, and
market_maker_service.py is stored in the `platform_parameters` table
(plus the placement payout curve in `dividend_placement_curve`) rather
than hardcoded, and is readable/writable through the admin API (see
app/api/v1/admin.py). The values below in `DEFAULTS` are only used to
seed a row the first time it's read -- after that, the database is the
source of truth, and changing a value here in code has no effect on an
already-running system (that's the point: change it via the API without
a deploy).

If you DO want to change a starting default before you've gone live,
edit the numbers in `DEFAULTS` below and in
app/engine/dividend_calculator.DEFAULT_PLACEMENT_CURVE -- those are the
only two places starting values live.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from app.engine.dividend_calculator import DEFAULT_PLACEMENT_CURVE
from app.models.economic_params import DividendPlacementCurveEntry, PlatformParameter

# key -> (default value, human-readable description)
DEFAULTS: dict[str, tuple[Decimal, str]] = {
    "quick_trade.market_impact_coefficient": (
        Decimal("0.15"),
        "How steeply quick buy/sell price worsens as order size grows relative to synthetic liquidity depth. "
        "See app/engine/quick_trade_pricing.py.",
    ),
    "quick_trade.synthetic_depth_fraction": (
        Decimal("0.01"),
        "Synthetic (House) liquidity depth for quick orders, as a fraction of a player's shares outstanding.",
    ),
    "quick_trade.synthetic_depth_min": (
        Decimal("100"),
        "Floor on synthetic liquidity depth, in shares, so newly-IPO'd/thinly-held players aren't absurdly illiquid.",
    ),
    "dividend.platform_fee_pct": (
        Decimal("0.0"),
        "Fraction of each dividend pool kept by the platform before distribution to shareholders. "
        "Also a simulation inflation-control lever.",
    ),
    "bot_liquidity.num_levels": (
        Decimal("5"),
        "Number of bid/ask ladder levels the House posts per side when providing bot liquidity.",
    ),
    "bot_liquidity.step_pct": (
        Decimal("0.01"),
        "Percentage price step between consecutive bot ladder levels.",
    ),
    "bot_liquidity.spread_pct": (
        Decimal("0.02"),
        "Percentage offset of the innermost bot bid/ask quote from the center price.",
    ),
    "bot_liquidity.qty_per_level": (
        Decimal("50"),
        "Shares posted per bot ladder level, per side.",
    ),
    "fees.transaction_fee_pct": (
        Decimal("0.0025"),
        "Flat percentage fee charged to the TAKER (aggressor) side of every trade fill -- maker side pays "
        "nothing. Matches the validated economy simulation's 0.25% transaction tax. Collected fees are "
        "routed to the House account as a permanent sink on the user side of the ledger (see "
        "app/services/order_service.py).",
    ),
    "auction.entry_fee": (
        Decimal("10000"),
        "One-time flat fee charged when a user joins a player-share IPO auction round (not per bid -- "
        "one fee unlocks bidding on every player in that round). Matches the simulation's $10,000 flat "
        "auction entry fee. See app/services/auction_service.py.",
    ),
    "dividend.cash_cup_pool": (
        Decimal("300000"),
        "Fixed synthetic dividend pool paid out for a Cash Cup tournament, used instead of a real-world "
        "prize pool. Matches the simulation's locked-in economics (36 cash cups/chapter x $300k = "
        "$10.8M). See economic_params_service.get_fixed_tournament_pool.",
    ),
    "dividend.fncs_pool": (
        Decimal("1500000"),
        "Fixed synthetic dividend pool paid out for an FNCS qualifier/finals tournament. Matches the "
        "simulation's locked-in economics (3 FNCS/chapter x $1.5M = $4.5M).",
    ),
    "dividend.global_pool": (
        Decimal("3000000"),
        "Fixed synthetic dividend pool paid out for the Global Championship tournament. Matches the "
        "simulation's locked-in economics (1 Global/chapter x $3M = $3M).",
    ),
    "wallet.starting_balance": (
        Decimal("1000000"),
        "Fantasy cash every new user is credited with automatically at registration, matching the "
        "simulation's $1,000,000-per-participant starting capital (see app/api/v1/auth.py). This is the "
        "ONLY source of starting cash -- the self-serve /wallet/deposit endpoint is admin-gated for "
        "top-ups so the simulated economy's total money supply stays meaningful.",
    ),
    # --- Bot trading population (app/services/bot_trading_service.py) ---
    # Ported from, but not identical to, the validated Python economy
    # simulator's SimConfig -- the live backend has no rumor/news/ELO
    # systems, so only the archetypes with a real live-data equivalent
    # were carried over. See bot_trading_service.py's module docstring
    # for exactly which simulator strategies were kept, dropped, or
    # simplified, and why.
    "bots.population_size": (
        Decimal("40"),
        "Target number of bot trader accounts to maintain. Each admin-triggered or scheduled tick tops "
        "the population up to this count if any bots are missing, but never removes existing bots.",
    ),
    "bots.participation_rate": (
        Decimal("0.4"),
        "Fraction of the bot population that acts on any given tick (matches the simulator's default). "
        "Keeps the whole population from hammering the order book simultaneously every tick.",
    ),
    "bots.max_trade_cash_fraction": (
        Decimal("0.25"),
        "Ceiling on how much of a bot's available cash it will commit to a single buy, before its "
        "per-strategy size multiplier and a random 30-100% dampener are applied.",
    ),
    "bots.max_trade_share_fraction": (
        Decimal("0.5"),
        "Ceiling on what fraction of a bot's own holding of a player it will sell in a single order, "
        "before its per-strategy size multiplier and a random 40-100% dampener are applied.",
    ),
    "bots.limit_order_probability": (
        Decimal("0.5"),
        "Default chance a bot places a resting limit order instead of an immediate quick order, for "
        "strategies without their own override (see STRATEGY_PROFILE in bot_trading_service.py).",
    ),
    "bots.limit_order_offset": (
        Decimal("0.03"),
        "How far off the current price a bot's limit order is placed: buys at price*(1-offset), sells "
        "at price*(1+offset). This is exactly the kind of 'probably won't fill' resting order that keeps "
        "the book looking like a real market without necessarily executing.",
    ),
    "bots.max_liquidity_take_fraction": (
        Decimal("0.6"),
        "Ceiling on how much of the visible opposite-side book depth a bot's quick order will sweep in "
        "one go, so a single bot can't single-handedly drain the book in one tick.",
    ),
    "bots.mm_quote_size_fraction": (
        Decimal("0.05"),
        "For the liquidity_provider archetype: fraction of its cash (bid side) or holding (ask side, x4) "
        "quoted per player per tick.",
    ),
    "bots.mm_spread_offset": (
        Decimal("0.02"),
        "For the liquidity_provider archetype: half-spread around the current price for its bid/ask quotes.",
    ),
}

# Tournament tiers that use a fixed synthetic dividend pool instead of a
# real-world prize pool, and which DEFAULTS key holds that pool's dollar
# amount. Keyed by app.models.tournament.TournamentType value. Tournament
# types not listed here (MAJOR, OTHER) fall back to the original behavior:
# an admin-entered `Tournament.prize_pool` split by the placement curve, or
# an exact `PlacementResult.prize_won` per player if that's known.
FIXED_POOL_PARAM_BY_TOURNAMENT_TYPE: dict[str, str] = {
    "cash_cup": "dividend.cash_cup_pool",
    "fncs_qualifier": "dividend.fncs_pool",
    "fncs_finals": "dividend.fncs_pool",
    "global_championship": "dividend.global_pool",
}


def get_fixed_tournament_pool(db: Session, tournament_type: str) -> Decimal | None:
    """Returns the fixed synthetic pool amount for this tournament type
    (per the locked-in economy design), or None if this tournament type
    should use its own admin-entered `prize_pool` instead (see
    FIXED_POOL_PARAM_BY_TOURNAMENT_TYPE above)."""
    param_key = FIXED_POOL_PARAM_BY_TOURNAMENT_TYPE.get(
        tournament_type.value if hasattr(tournament_type, "value") else tournament_type
    )
    if param_key is None:
        return None
    return get_param(db, param_key)


def get_param(db: Session, key: str) -> Decimal:
    row = db.get(PlatformParameter, key)
    if row is None:
        if key not in DEFAULTS:
            raise KeyError(f"Unknown platform parameter '{key}'")
        default_value, description = DEFAULTS[key]
        row = PlatformParameter(key=key, value=default_value, description=description)
        db.add(row)
        db.flush()
    return row.value


def set_param(db: Session, key: str, value: Decimal, admin_id: uuid.UUID | None = None) -> PlatformParameter:
    row = db.get(PlatformParameter, key)
    if row is None:
        _, description = DEFAULTS.get(key, (None, None))
        row = PlatformParameter(key=key, value=value, description=description, updated_by_admin_id=admin_id)
        db.add(row)
    else:
        row.value = value
        row.updated_by_admin_id = admin_id
    db.flush()
    return row


def get_all_params(db: Session) -> list[PlatformParameter]:
    """Ensures every key in DEFAULTS has a row (seeding any missing ones),
    then returns all of them -- used by the admin "list current
    parameters" endpoint."""
    for key in DEFAULTS:
        get_param(db, key)
    db.flush()
    return db.query(PlatformParameter).order_by(PlatformParameter.key).all()


def get_placement_curve(db: Session) -> dict[int, Decimal]:
    rows = db.query(DividendPlacementCurveEntry).all()
    if not rows:
        for placement, fraction in DEFAULT_PLACEMENT_CURVE.items():
            db.add(DividendPlacementCurveEntry(placement=placement, pool_fraction=fraction))
        db.flush()
        rows = db.query(DividendPlacementCurveEntry).all()
    return {row.placement: row.pool_fraction for row in rows}


def set_placement_curve_entry(db: Session, placement: int, pool_fraction: Decimal) -> DividendPlacementCurveEntry:
    row = db.get(DividendPlacementCurveEntry, placement)
    if row is None:
        row = DividendPlacementCurveEntry(placement=placement, pool_fraction=pool_fraction)
        db.add(row)
    else:
        row.pool_fraction = pool_fraction
    db.flush()
    return row
