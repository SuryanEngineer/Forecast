"""
Bot trading population -- keeps the order book populated with resting and
executed orders that look like real human activity, so the market isn't a
ghost town while the real user base is small.

This is a NEW system for the live backend. It is inspired by, but not a
verbatim port of, the validated Python economy simulator's bot/human
trading logic (see forecast_sim/trading.py and forecast_sim/strategies.py
in the separate simulator project -- that code was written purely to
validate the platform's economics before this backend existed, and was
never connected to it). Differences from the simulator, and why:

  * The simulator has 15 trading-strategy archetypes; several of them
    (rumor_trader, news_trader, smart_money, speculator, team_loyalist)
    key off systems that simply don't exist in the live product yet --
    there's no synthetic rumor feed, no news-sentiment score, no insider-
    information mechanic, and no per-user "favorite team" concept. Rather
    than fake those signals, this module implements the subset of
    archetypes that map cleanly onto data that's actually live in this
    database: recent price movement (PriceSnapshot), recent tournament
    performance (PlacementResult), and a player's current price relative
    to its own history. When the platform grows a real news/rumor/social
    layer (see the "Fortnite esports data/API integration" task), more
    archetypes can be added here without touching anything else.

  * The simulator uses a seeded numpy Generator so a whole run is exactly
    reproducible. This module uses the stdlib `random` module instead, so
    as not to add a numpy dependency to a production web service for a
    feature that doesn't need bit-for-bit reproducibility (bot orders
    only need to look plausible, not replay identically run to run).

  * The simulator has an explicit order-max-age concept (stale resting
    orders expire after N rounds). This module does not implement order
    expiry yet -- per the roadmap discussion that motivated this file,
    bot orders that never fill are considered a feature, not a bug (a
    realistic order book has plenty of orders that never execute). The
    practical consequence: a bot's cash/shares can gradually get tied up
    in resting orders across many ticks. The `liquidity_provider`
    archetype self-corrects (it cancels and re-quotes every tick it
    acts), but the directional archetypes below do not. If bots start
    going quiet over time because they're out of available balance, an
    order-expiry sweep (cancel-and-release anything older than N hours)
    would be the natural follow-up -- deliberately left out of this pass
    to keep it reviewable in one piece.

Every order a bot places goes through the exact same
order_service.place_limit_order / place_quick_order functions a human's
browser click would call -- there is no separate, less-safe code path for
bot money movement. A bot is a completely ordinary User row (see
ensure_bot_population below); `app/models/bot.py`'s BotProfile table is
just the extra bookkeeping (which strategy, which players a market-maker
bot quotes) that a human account doesn't need.
"""
from __future__ import annotations

import random
import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.bot import BotProfile
from app.models.order import Order, OrderSide, OrderStatus
from app.models.player import Player, Position, PriceSnapshot
from app.models.tournament import PlacementResult
from app.models.user import User, UserRole
from app.services import economic_params_service, order_service, wallet_service
from app.services.exceptions import ServiceError

# Renormalized subset of the simulator's `trading_strategy_weights` --
# every archetype here has a real live-data signal behind it (see module
# docstring for which ones were dropped and why).
STRATEGY_WEIGHTS: dict[str, float] = {
    "momentum_trader": 0.15,
    "contrarian": 0.10,
    "value_investor": 0.12,
    "dividend_hunter": 0.12,
    "whale": 0.05,
    "scalper": 0.08,
    "panic_seller": 0.08,
    "index_investor": 0.10,
    "random": 0.10,
    "liquidity_provider": 0.10,
}

# size_mult: multiplier on normal order sizing. skip_prob: chance this
# archetype sits out a tick it was otherwise selected to act on.
# limit_prob_override: this archetype's own limit-vs-quick coin flip
# probability, or None to use the shared `bots.limit_order_probability`.
# All three ported directly from the simulator's STRATEGY_PROFILE for the
# archetypes that survived the cut.
STRATEGY_PROFILE: dict[str, dict] = {
    "whale": {"size_mult": Decimal("3.0"), "skip_prob": 0.0, "limit_prob_override": Decimal("0.3")},
    "scalper": {"size_mult": Decimal("0.3"), "skip_prob": 0.0, "limit_prob_override": Decimal("0.15")},
    "panic_seller": {"size_mult": Decimal("1.4"), "skip_prob": 0.0, "limit_prob_override": Decimal("0.1")},
    "value_investor": {"size_mult": Decimal("0.9"), "skip_prob": 0.2, "limit_prob_override": Decimal("0.7")},
    "index_investor": {"size_mult": Decimal("0.5"), "skip_prob": 0.0, "limit_prob_override": Decimal("0.6")},
}
DEFAULT_PROFILE = {"size_mult": Decimal("1.0"), "skip_prob": 0.0, "limit_prob_override": None}

_STRATEGY_LABELS: dict[str, str] = {
    "momentum_trader": "Momentum",
    "contrarian": "Contrarian",
    "value_investor": "Value",
    "dividend_hunter": "Dividend Hunter",
    "whale": "Whale",
    "scalper": "Scalper",
    "panic_seller": "Panic Seller",
    "index_investor": "Index",
    "random": "Wildcard",
    "liquidity_provider": "Market Maker",
}

# Flat per-tick chance an active bot that holds *something* considers
# selling instead of buying -- matches the simulator's hardcoded 0.45.
SELL_CONSIDERATION_PROBABILITY = 0.45


# --- Fair-value anchoring -------------------------------------------
# Before this, a player's power_rating (and the ipo_price it scales --
# see player_service.ipo_price_for_rating) had zero ongoing influence on
# bot trading: every strategy above only ever looked at momentum/
# contrarian %-change signals, recent placement (dividend_hunter only),
# or pure randomness, with no persistent force tying price back to
# skill. Two elite and journeyman players could random-walk to the same
# price with nothing pulling them apart. `fair_value` (ipo_price scaled
# by a bounded "recent form" multiplier) plus `_weighted_pick` below
# fixes that: buy/sell target selection is now *biased* (never forced --
# there's still real randomness) toward whichever candidates are most
# mispriced relative to their own fair value.
PLACEMENT_FORM_MAX_BONUS = 0.25
PLACEMENT_FORM_MAX_PENALTY = -0.15
PLACEMENT_FORM_NEUTRAL_PLACEMENT = 12
PLACEMENT_FORM_SENSITIVITY = 60

VALUE_WEIGHT_MIN = 0.15
VALUE_WEIGHT_MAX = 6.0


def _placement_form_multiplier(placement: int | None) -> float:
    if placement is None:
        return 1.0
    raw = (PLACEMENT_FORM_NEUTRAL_PLACEMENT - placement) / PLACEMENT_FORM_SENSITIVITY
    return 1 + max(PLACEMENT_FORM_MAX_PENALTY, min(PLACEMENT_FORM_MAX_BONUS, raw))


def _compute_fair_value(ipo_price: Decimal, best_recent_placement: int | None) -> Decimal:
    multiplier = Decimal(str(round(_placement_form_multiplier(best_recent_placement), 6)))
    return ipo_price * multiplier


def _value_weight(ratio: Decimal) -> float:
    """Clamp a fair-value-vs-price ratio into a usable weighted-lottery
    weight -- bounded both directions so one wildly mispriced player
    can't make `_weighted_pick` nearly deterministic."""
    return max(VALUE_WEIGHT_MIN, min(VALUE_WEIGHT_MAX, float(ratio)))


def _weighted_pick(rng: random.Random, items: list[uuid.UUID], weight_fn) -> uuid.UUID:
    """Weighted lottery over `items` using `weight_fn(item)` as the
    relative weight -- like `_weighted_choice` above, but generalized to
    arbitrary items instead of a fixed strategy-name dict, and used to
    bias (not force) target selection toward fair-value mispricing.
    Falls back to a uniform choice if every weight comes back <= 0."""
    weights = [max(weight_fn(item), 0.0) for item in items]
    total = sum(weights)
    if total <= 0:
        return rng.choice(items)
    r = rng.uniform(0, total)
    upto = 0.0
    for item, w in zip(items, weights):
        upto += w
        if upto >= r:
            return item
    return items[-1]


@dataclass
class MarketSnapshot:
    """Read-only per-tick bundle every bot's decision this tick is made
    against, so every bot in the same tick sees a consistent view of the
    market (built once, not re-queried per bot)."""

    player_ids: list[uuid.UUID]
    price: dict[uuid.UUID, Decimal] = field(default_factory=dict)
    pct_change: dict[uuid.UUID, Decimal] = field(default_factory=dict)
    best_recent_placement: dict[uuid.UUID, int] = field(default_factory=dict)
    fair_value: dict[uuid.UUID, Decimal] = field(default_factory=dict)


def _current_price(db: Session, player: Player) -> Decimal:
    """Last traded price, falling back to IPO price -- deliberately kept
    as its own small query here (rather than importing order_service's
    private `_reference_price`) since it's cheap and avoids a cross-module
    dependency on another service's underscore-prefixed helper."""
    last = (
        db.query(PriceSnapshot)
        .filter(PriceSnapshot.player_id == player.id)
        .order_by(PriceSnapshot.recorded_at.desc())
        .first()
    )
    return last.price if last else player.ipo_price


def _build_snapshot(db: Session) -> MarketSnapshot:
    players = db.query(Player).filter(Player.is_active.is_(True)).all()
    player_ids = [p.id for p in players]
    price = {p.id: _current_price(db, p) for p in players}

    # Up to 20 most recent price points per player, for momentum/
    # contrarian/value signals. One query for every player instead of one
    # per player -- same prototype-scale trade-off leaderboard_service.py
    # already makes and documents for itself.
    history: dict[uuid.UUID, list[Decimal]] = {pid: [] for pid in player_ids}
    if player_ids:
        for row in (
            db.query(PriceSnapshot)
            .filter(PriceSnapshot.player_id.in_(player_ids))
            .order_by(PriceSnapshot.recorded_at.desc())
            .limit(4000)
            .all()
        ):
            bucket = history.setdefault(row.player_id, [])
            if len(bucket) < 20:
                bucket.append(row.price)

    pct_change: dict[uuid.UUID, Decimal] = {}
    for pid, prices in history.items():
        if len(prices) >= 2 and prices[-1] > 0:
            pct_change[pid] = (prices[0] - prices[-1]) / prices[-1]
        else:
            pct_change[pid] = Decimal("0")

    best_recent_placement: dict[uuid.UUID, int] = {}
    if player_ids:
        for row in (
            db.query(PlacementResult)
            .filter(PlacementResult.player_id.in_(player_ids))
            .order_by(PlacementResult.created_at.desc())
            .limit(4000)
            .all()
        ):
            best_recent_placement.setdefault(row.player_id, row.placement)

    fair_value = {
        p.id: _compute_fair_value(p.ipo_price, best_recent_placement.get(p.id)) for p in players
    }

    return MarketSnapshot(
        player_ids=player_ids,
        price=price,
        pct_change=pct_change,
        best_recent_placement=best_recent_placement,
        fair_value=fair_value,
    )


def _weighted_choice(rng: random.Random, weights: dict[str, float]) -> str:
    keys = list(weights.keys())
    values = list(weights.values())
    return rng.choices(keys, weights=values, k=1)[0]


def _bot_display_name(n: int, strategy: str) -> str:
    return f"{_STRATEGY_LABELS.get(strategy, 'Trader')} Bot #{n}"


def ensure_bot_population(db: Session, target_count: int, rng: random.Random) -> int:
    """Tops the bot population up to `target_count` if it's short, never
    removes bots. Each new bot is a completely ordinary registered User
    (same starting balance as a real signup) plus a BotProfile row tagging
    its strategy. Returns how many new bots were created."""
    current = db.query(BotProfile).count()
    to_create = target_count - current
    if to_create <= 0:
        return 0

    starting_balance = economic_params_service.get_param(db, "wallet.starting_balance")
    active_player_ids = [p.id for p in db.query(Player).filter(Player.is_active.is_(True)).all()]

    created = 0
    next_n = current
    attempts = 0
    while created < to_create and attempts < to_create * 3:
        attempts += 1
        next_n += 1
        email = f"bot-{next_n}@bots.forecast.internal"
        if db.query(User).filter(User.email == email).one_or_none() is not None:
            continue  # number already taken by a bot from an earlier partial run -- skip ahead

        strategy = _weighted_choice(rng, STRATEGY_WEIGHTS)
        user = User(
            email=email,
            password_hash="!disabled!",  # bots never log in, same convention as the House account
            display_name=_bot_display_name(next_n, strategy),
            role=UserRole.USER,
            is_active=True,
        )
        db.add(user)
        db.flush()

        wallet_service.get_or_create_wallet(db, user.id)
        wallet_service.deposit(db, user.id, starting_balance, memo="Bot trader starting capital")

        mm_player_ids = None
        if strategy == "liquidity_provider" and active_player_ids:
            k = min(4, len(active_player_ids))
            mm_player_ids = [str(pid) for pid in rng.sample(active_player_ids, k=k)]

        db.add(BotProfile(user_id=user.id, strategy=strategy, mm_player_ids=mm_player_ids))
        db.flush()
        created += 1

    return created


def _pick_buy_target(strategy: str, snapshot: MarketSnapshot, rng: random.Random) -> uuid.UUID | None:
    candidates = [pid for pid in snapshot.player_ids if snapshot.price.get(pid, Decimal("0")) > 0]
    if not candidates:
        return None

    if strategy == "momentum_trader":
        candidates.sort(key=lambda pid: snapshot.pct_change.get(pid, Decimal("0")), reverse=True)
    elif strategy == "contrarian" or strategy == "value_investor":
        # Buy what's recently lagged -- "contrarian" bets on reversion,
        # "value_investor" treats a dip as a discount. Same signal,
        # different narrative; the size/skip/limit-prob profile is what
        # actually differentiates their behavior (see STRATEGY_PROFILE).
        candidates.sort(key=lambda pid: snapshot.pct_change.get(pid, Decimal("0")))
    elif strategy == "dividend_hunter":
        with_placement = [pid for pid in candidates if pid in snapshot.best_recent_placement]
        pool = with_placement if with_placement else candidates
        pool.sort(key=lambda pid: snapshot.best_recent_placement.get(pid, 999))
        candidates = pool
    elif strategy == "whale":
        candidates.sort(key=lambda pid: snapshot.price.get(pid, Decimal("0")), reverse=True)
    else:
        # index_investor, scalper, panic_seller, random -- no directional
        # opinion, just pick something roughly at random.
        rng.shuffle(candidates)

    top = candidates[: max(5, len(candidates) // 4)]
    if not top:
        return None

    def _buy_weight(pid: uuid.UUID) -> float:
        fv = snapshot.fair_value.get(pid)
        p = snapshot.price.get(pid)
        if not fv or not p or p <= 0:
            return 1.0
        return _value_weight(fv / p)  # underpriced-vs-fair-value -> higher weight

    return _weighted_pick(rng, top, _buy_weight)


def _pick_sell_target(strategy: str, holdings: dict[uuid.UUID, Position], snapshot: MarketSnapshot, rng: random.Random) -> uuid.UUID | None:
    owned = [pid for pid, pos in holdings.items() if pos.available_quantity > 0]
    if not owned:
        return None

    if strategy == "panic_seller":
        return rng.choice(owned)  # dumps something at random, no analysis -- that's the archetype
    if strategy == "momentum_trader":
        owned.sort(key=lambda pid: snapshot.pct_change.get(pid, Decimal("0")))  # cut the laggards
    elif strategy in ("contrarian", "value_investor"):
        owned.sort(key=lambda pid: snapshot.pct_change.get(pid, Decimal("0")), reverse=True)  # take profit on the winners
    else:
        rng.shuffle(owned)

    top = owned[: max(3, len(owned) // 3)]
    if not top:
        return None

    def _sell_weight(pid: uuid.UUID) -> float:
        fv = snapshot.fair_value.get(pid)
        p = snapshot.price.get(pid)
        if not fv or fv <= 0:
            return 1.0
        return _value_weight(p / fv) if p else 1.0  # overpriced-vs-fair-value -> higher weight

    return _weighted_pick(rng, top, _sell_weight)


def _execute_buy(db: Session, user_id: uuid.UUID, player_id: uuid.UUID, qty: int, ref_price: Decimal, params: dict, profile: dict, rng: random.Random) -> bool:
    if qty <= 0:
        return False
    limit_prob = profile["limit_prob_override"] if profile["limit_prob_override"] is not None else params["limit_order_probability"]
    if rng.random() < float(limit_prob):
        limit_price = (ref_price * (Decimal("1") - params["limit_order_offset"])).quantize(Decimal("0.01"))
        if limit_price <= 0:
            return False
        order_service.place_limit_order(db, user_id, player_id, OrderSide.BUY, limit_price, qty, is_bot=True)
    else:
        order_service.place_quick_order(db, user_id, player_id, OrderSide.BUY, qty, is_bot=True)
    return True


def _execute_sell(db: Session, user_id: uuid.UUID, player_id: uuid.UUID, qty: int, ref_price: Decimal, params: dict, profile: dict, rng: random.Random) -> bool:
    if qty <= 0:
        return False
    limit_prob = profile["limit_prob_override"] if profile["limit_prob_override"] is not None else params["limit_order_probability"]
    if rng.random() < float(limit_prob):
        limit_price = (ref_price * (Decimal("1") + params["limit_order_offset"])).quantize(Decimal("0.01"))
        order_service.place_limit_order(db, user_id, player_id, OrderSide.SELL, limit_price, qty, is_bot=True)
    else:
        order_service.place_quick_order(db, user_id, player_id, OrderSide.SELL, qty, is_bot=True)
    return True


def _run_bot_agent(db: Session, bot_user: User, profile_row: BotProfile, snapshot: MarketSnapshot, params: dict, rng: random.Random) -> bool:
    """The generic (non-market-maker) directional strategies. Mirrors the
    simulator's unified per-agent decision shape: consider selling first
    if the bot holds anything, otherwise buy. Raises ServiceError/
    ValueError up to the caller on failure (e.g. insufficient funds) --
    the tick loop treats that as 'this bot sat out this tick', not a
    crash."""
    profile = STRATEGY_PROFILE.get(profile_row.strategy, DEFAULT_PROFILE)
    if profile["skip_prob"] > 0 and rng.random() < profile["skip_prob"]:
        return False

    wallet = wallet_service.get_or_create_wallet(db, bot_user.id)
    holdings = {
        pos.player_id: pos
        for pos in db.query(Position).filter(Position.user_id == bot_user.id, Position.quantity > 0).all()
    }

    do_sell = bool(holdings) and rng.random() < SELL_CONSIDERATION_PROBABILITY

    if do_sell:
        player_id = _pick_sell_target(profile_row.strategy, holdings, snapshot, rng)
        if player_id is None:
            return False
        have = holdings[player_id].available_quantity
        dampener = Decimal(str(round(rng.uniform(0.4, 1.0), 4)))
        qty = max(1, int(have * params["max_trade_share_fraction"] * profile["size_mult"] * dampener))
        qty = min(qty, have)
        ref_price = snapshot.price.get(player_id, Decimal("0"))
        return _execute_sell(db, bot_user.id, player_id, qty, ref_price, params, profile, rng)
    else:
        player_id = _pick_buy_target(profile_row.strategy, snapshot, rng)
        if player_id is None:
            return False
        price = snapshot.price.get(player_id)
        if not price or price <= 0:
            return False
        dampener = Decimal(str(round(rng.uniform(0.3, 1.0), 4)))
        spend = min(wallet.available_balance, wallet.available_balance * params["max_trade_cash_fraction"] * profile["size_mult"] * dampener)
        qty = int(spend // price)
        return _execute_buy(db, bot_user.id, player_id, qty, price, params, profile, rng)


def _run_liquidity_provider(db: Session, bot_user: User, profile_row: BotProfile, snapshot: MarketSnapshot, params: dict, rng: random.Random) -> bool:
    """Quotes both sides of up to 2 of its assigned players every tick it
    acts. Unlike the directional strategies, this one cancels its own
    previous resting orders on a player before requoting -- a real market
    maker refreshes its quotes rather than piling up an ever-growing stack
    of stale ones (see module docstring for why the directional
    strategies deliberately do NOT do this)."""
    assigned = [uuid.UUID(s) for s in (profile_row.mm_player_ids or [])]
    if not assigned:
        return False
    targets = list(assigned)
    rng.shuffle(targets)
    targets = targets[:2]

    acted = False
    for player_id in targets:
        price = snapshot.price.get(player_id)
        if not price or price <= 0:
            continue

        open_orders = (
            db.query(Order)
            .filter(
                Order.user_id == bot_user.id,
                Order.player_id == player_id,
                Order.status.in_([OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED]),
            )
            .all()
        )
        for order in open_orders:
            try:
                order_service.cancel_order(db, bot_user.id, order.id)
            except ServiceError:
                pass

        wallet = wallet_service.get_or_create_wallet(db, bot_user.id)
        spread = params["mm_spread_offset"]
        quote_fraction = params["mm_quote_size_fraction"]

        bid_price = (price * (Decimal("1") - spread)).quantize(Decimal("0.01"))
        if bid_price > 0:
            budget = wallet.available_balance * quote_fraction
            qty = int(budget // bid_price)
            if qty > 0:
                try:
                    order_service.place_limit_order(db, bot_user.id, player_id, OrderSide.BUY, bid_price, qty, is_bot=True)
                    acted = True
                except ServiceError:
                    pass

        position = db.query(Position).filter(Position.user_id == bot_user.id, Position.player_id == player_id).one_or_none()
        have = position.available_quantity if position is not None else 0
        if have > 0:
            ask_price = (price * (Decimal("1") + spread)).quantize(Decimal("0.01"))
            ask_qty = min(have, max(1, int(have * quote_fraction * 4)))
            try:
                order_service.place_limit_order(db, bot_user.id, player_id, OrderSide.SELL, ask_price, ask_qty, is_bot=True)
                acted = True
            except ServiceError:
                pass

    return acted


def _load_params(db: Session) -> dict[str, Decimal]:
    keys = [
        "bots.population_size",
        "bots.participation_rate",
        "bots.max_trade_cash_fraction",
        "bots.max_trade_share_fraction",
        "bots.limit_order_probability",
        "bots.limit_order_offset",
        "bots.max_liquidity_take_fraction",
        "bots.mm_quote_size_fraction",
        "bots.mm_spread_offset",
    ]
    return {key.split(".", 1)[1]: economic_params_service.get_param(db, key) for key in keys}


def run_bot_tick(db: Session, rng: random.Random | None = None) -> dict:
    """Runs one full tick of bot activity: tops up the population if it's
    short, picks a random active subset, and has each of them take one
    action (or sit out). Commits per-bot so one bot's failure can't roll
    back another's success. Safe to call repeatedly (from the background
    loop in app/main.py, or on-demand via POST /admin/bots/tick)."""
    rng = rng or random.Random()
    params = _load_params(db)

    ensure_bot_population(db, int(params["population_size"]), rng)
    db.commit()

    bots = db.query(BotProfile).all()
    if not bots:
        return {"population": 0, "active": 0, "actions": 0, "errors": 0}

    n_active = max(1, int(len(bots) * float(params["participation_rate"])))
    active = rng.sample(bots, k=min(n_active, len(bots)))

    snapshot = _build_snapshot(db)
    actions = 0
    errors = 0

    for profile_row in active:
        bot_user = db.get(User, profile_row.user_id)
        if bot_user is None or not bot_user.is_active:
            continue
        try:
            if profile_row.strategy == "liquidity_provider":
                acted = _run_liquidity_provider(db, bot_user, profile_row, snapshot, params, rng)
            else:
                acted = _run_bot_agent(db, bot_user, profile_row, snapshot, params, rng)
            if acted:
                db.commit()
                actions += 1
            else:
                db.rollback()
        except (ServiceError, ValueError):
            db.rollback()
            errors += 1

    return {"population": len(bots), "active": len(active), "actions": actions, "errors": errors}
