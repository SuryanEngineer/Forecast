"""
Bot trading population -- keeps the market populated with resting and executed orders that look like real human
activity, so the order book isn't a ghost town while the real user base is small.

Every order a bot places goes through the same order_service.place_limit_order / place_quick_order a human's click
would call; a bot is an ordinary User row plus a BotProfile row (strategy + market-making assignment).

How a bot decides (rebuilt; replaces the earlier "pick from a ranked list" logic)
--------------------------------------------------------------------------------
Each tick one shared MarketSnapshot is built from live data, containing five per-player signals, each scaled to
roughly -1..+1:

  value  -- ln(fair value / price). Fair value is the player's IPO price scaled by a recency-weighted, career-long
            expected-dividend estimate (every historical placement is run through the same payout curve real
            dividends use, against that tournament's own field size and pool), normalized against the roster median.
  yld    -- expected dividend yield per share: the player's recency-weighted expected payout per tournament (net of the
            platform fee, divided by shares outstanding) blended with the per-share dividends actually paid to holders,
            relative to the roster median yield.
  mom    -- recent price momentum (last ~20 price points).
  form   -- recent results versus the player's own career (average of the last 3 placement-curve fractions vs all):
            positive = trending up, negative = slumping. Ordered by tournament START time, so backfilled history is
            ranked correctly.
  event  -- dividend timing. Dividends are paid on shares held when a tournament STARTS, so a player entered in an
            event starting soon is worth owning right now (1.0 within a day, fading to 0.25 at two weeks); right
            after the start the dividend has been "captured" and the signal turns mildly negative (an ex-dividend dip).

Each strategy archetype weighs those signals differently (e.g. dividend_hunter leans on yld + event, value_investor on
value, momentum_trader on mom + form, contrarian fades mom), and every individual bot has a stable personality derived
from its user id (its weights are nudged +/-25%, it watches 20-60 players per tick, caps any one position at its own
fraction of portfolio, takes profit / cuts losses at its own thresholds). Bots score a random watchlist plus their
holdings, weigh buying against selling by how much cash they have idle, size orders by conviction, choose limit vs
quick orders by conviction (confident bots hit the market; patient ones rest limits), and keep their own order stack
tidy by cancelling stale orders.

Market makers (strategy "liquidity_provider") are assigned so EVERY active player is quoted by at least
MM_COVERAGE makers; they requote around a mid that leans toward fair value, widen their spread when a stock is
volatile, and leave still-fresh quotes alone.
"""
from __future__ import annotations

import math
import random
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.engine.dividend_calculator import placement_payout_fraction
from app.models.bot import BotProfile
from app.models.dividend import DividendPayout, DividendPayoutStatus
from app.models.order import Order, OrderSide, OrderStatus
from app.models.player import Player, Position, PriceSnapshot
from app.models.tournament import PlacementResult, Tournament, TournamentEntrant, TournamentStatus
from app.models.user import User, UserRole
from app.services import economic_params_service, order_service, wallet_service
from app.services.bot_names import generate_username
from app.services.exceptions import ServiceError

STRATEGY_WEIGHTS: dict[str, float] = {
    "momentum_trader": 0.15,
    "contrarian": 0.10,
    "value_investor": 0.14,
    "dividend_hunter": 0.15,
    "whale": 0.05,
    "scalper": 0.08,
    "panic_seller": 0.07,
    "index_investor": 0.10,
    "random": 0.06,
    "liquidity_provider": 0.10,
}

# Per-archetype signal weights. conc = diversification pressure (penalises over-concentrated positions).
SIGNAL_WEIGHTS: dict[str, dict[str, float]] = {
    "momentum_trader": dict(value=0.2, yld=0.2, mom=1.5, form=0.7, event=0.4, conc=0.4, noise=0.25),
    "contrarian": dict(value=1.0, yld=0.3, mom=-0.9, form=0.1, event=0.2, conc=0.4, noise=0.25),
    "value_investor": dict(value=1.6, yld=0.7, mom=0.0, form=0.3, event=0.3, conc=0.5, noise=0.15),
    "dividend_hunter": dict(value=0.3, yld=1.7, mom=0.1, form=0.6, event=1.1, conc=0.5, noise=0.15),
    "whale": dict(value=0.9, yld=0.9, mom=0.2, form=0.6, event=0.5, conc=0.3, noise=0.10),
    "scalper": dict(value=0.3, yld=0.1, mom=0.5, form=0.1, event=0.1, conc=0.2, noise=0.90),
    "panic_seller": dict(value=0.1, yld=0.1, mom=1.0, form=1.0, event=0.2, conc=0.2, noise=0.60),
    "index_investor": dict(value=0.2, yld=0.2, mom=0.0, form=0.1, event=0.1, conc=1.8, noise=0.30),
    "random": dict(value=0.3, yld=0.2, mom=0.2, form=0.2, event=0.2, conc=0.3, noise=1.00),
}

# size_mult, optional limit-order probability override, chance to sit a tick out.
STRATEGY_PROFILE: dict[str, dict] = {
    "whale": {"size_mult": Decimal("3.0"), "skip_prob": 0.0, "limit_prob_override": Decimal("0.3")},
    "scalper": {"size_mult": Decimal("0.3"), "skip_prob": 0.0, "limit_prob_override": Decimal("0.15")},
    "panic_seller": {"size_mult": Decimal("1.4"), "skip_prob": 0.0, "limit_prob_override": Decimal("0.1")},
    "value_investor": {"size_mult": Decimal("0.9"), "skip_prob": 0.15, "limit_prob_override": Decimal("0.7")},
    "index_investor": {"size_mult": Decimal("0.5"), "skip_prob": 0.0, "limit_prob_override": Decimal("0.6")},
    "dividend_hunter": {"size_mult": Decimal("1.1"), "skip_prob": 0.05, "limit_prob_override": Decimal("0.55")},
}
DEFAULT_PROFILE = {"size_mult": Decimal("1.0"), "skip_prob": 0.0, "limit_prob_override": None}

TAKE_PROFIT = {"dividend_hunter": 0.60, "whale": 0.50, "value_investor": 0.45, "scalper": 0.05, "default": 0.30}
STOP_LOSS = {"panic_seller": -0.08, "momentum_trader": -0.12, "scalper": -0.05}
POSITION_CAP = {"whale": 0.30, "index_investor": 0.05, "scalper": 0.08, "dividend_hunter": 0.20, "default": 0.15}

BUY_FLOOR = -0.05     # a bot buys its best-scoring watchlist pick if that score clears this
SELL_FLOOR = 0.30     # ...and sells a holding only if its sell score clears this (bots prefer holding)
MIN_CASH_FRACTION = 0.03

# Market makers
MM_COVERAGE = 2            # every active player is quoted by at least this many makers
MM_PLAYERS_PER_TICK = 6
MM_PLAYERS_PER_MAKER = 25  # how many players one maker can reasonably cover (drives the minimum maker count)
MM_MIN_MAKERS = 8
MM_MAX_SKEW = 0.03         # mid leans toward fair value by at most 3%

ORDER_MAX_AGE = timedelta(hours=6)

# Fair-value construction (unchanged in spirit from the original: see module docstring).
HISTORY_RECENCY_DECAY = 0.85
HISTORY_MAX_RESULTS_PER_PLAYER = 20
PERFORMANCE_ELASTICITY = 0.5
PERFORMANCE_MULT_MIN = 0.4
PERFORMANCE_MULT_MAX = 3.0


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


# --- Career / dividend analytics ---------------------------------------------------------------------------------


def _tournament_pool_amounts(db: Session, tournament_ids: list[uuid.UUID]) -> dict[uuid.UUID, Decimal]:
    """The dividend pool each tournament pays (the tier's fixed synthetic pool scaled by region, or the tournament's
    own prize_pool). One batched query."""
    if not tournament_ids:
        return {}
    pools: dict[uuid.UUID, Decimal] = {}
    for t_id, tournament_type, region, prize_pool in (
        db.query(Tournament.id, Tournament.tournament_type, Tournament.region, Tournament.prize_pool)
        .filter(Tournament.id.in_(tournament_ids))
        .all()
    ):
        fixed_pool = economic_params_service.get_fixed_tournament_pool(db, tournament_type)
        if fixed_pool is not None:
            pools[t_id] = fixed_pool * economic_params_service.get_region_multiplier(db, region)
        elif prize_pool is not None:
            pools[t_id] = prize_pool
        else:
            pools[t_id] = Decimal("0")
    return pools


def _career_stats(db: Session, player_ids: list[uuid.UUID]) -> tuple[dict[uuid.UUID, Decimal], dict[uuid.UUID, float]]:
    """Returns (expected_value, form) per player.

    expected_value: recency-weighted average of what each past placement was worth as a dividend pool (placement run
    through the real payout curve against that tournament's own field size and pool). Missing = no history.
    form: recent (last 3) placement-curve fraction versus the player's own career average, clamped to -1..+1.
    Results are ordered by TOURNAMENT START TIME (not row-creation time), so a bulk historical backfill still reads
    in true chronological order."""
    if not player_ids:
        return {}, {}

    rows = (
        db.query(PlacementResult.player_id, PlacementResult.tournament_id, PlacementResult.placement)
        .join(Tournament, Tournament.id == PlacementResult.tournament_id)
        .filter(PlacementResult.player_id.in_(player_ids))
        .order_by(Tournament.start_time.desc().nullslast(), PlacementResult.created_at.desc())
        .limit(30000)
        .all()
    )
    if not rows:
        return {}, {}

    by_player: dict[uuid.UUID, list[tuple[uuid.UUID, int]]] = defaultdict(list)
    tournament_ids: set[uuid.UUID] = set()
    for player_id, tournament_id, placement in rows:
        by_player[player_id].append((tournament_id, placement))
        tournament_ids.add(tournament_id)

    field_size = {
        tid: n
        for tid, n in db.query(PlacementResult.tournament_id, func.count(PlacementResult.id))
        .filter(PlacementResult.tournament_id.in_(tournament_ids))
        .group_by(PlacementResult.tournament_id)
        .all()
    }
    pools = _tournament_pool_amounts(db, list(tournament_ids))
    curve = economic_params_service.get_placement_curve(db)
    decay = Decimal(str(HISTORY_RECENCY_DECAY))

    expected_value: dict[uuid.UUID, Decimal] = {}
    form: dict[uuid.UUID, float] = {}
    for player_id, results in by_player.items():
        recent = results[:HISTORY_MAX_RESULTS_PER_PLAYER]  # most-recent-first
        weighted_sum = Decimal("0")
        weight_total = Decimal("0")
        fractions: list[float] = []
        for rank, (tournament_id, placement) in enumerate(recent):
            max_placement = max(1, field_size.get(tournament_id, 1))
            fraction = placement_payout_fraction(placement, max_placement, curve)
            weight = decay**rank
            weighted_sum += pools.get(tournament_id, Decimal("0")) * fraction * weight
            weight_total += weight
            fractions.append(float(fraction))
        if weight_total > 0:
            expected_value[player_id] = weighted_sum / weight_total
        if len(fractions) >= 2:
            recent_avg = sum(fractions[:3]) / len(fractions[:3])
            career_avg = sum(fractions) / len(fractions)
            form[player_id] = _clamp((recent_avg - career_avg) / max(career_avg, 1e-9), -1.0, 1.0)
    return expected_value, form


def _expected_value_per_tournament(db: Session, player_ids: list[uuid.UUID]) -> dict[uuid.UUID, Decimal]:
    """Kept for callers/scripts that only want the expected-value half."""
    return _career_stats(db, player_ids)[0]


def _compute_fair_value(ipo_price: Decimal, own_ev: Decimal | None, roster_median_ev: Decimal | None) -> Decimal:
    if own_ev is None or roster_median_ev is None or roster_median_ev <= 0:
        return ipo_price
    ratio = float(own_ev / roster_median_ev)
    multiplier = ratio**PERFORMANCE_ELASTICITY if ratio > 0 else 0.0
    multiplier = _clamp(multiplier, PERFORMANCE_MULT_MIN, PERFORMANCE_MULT_MAX)
    return ipo_price * Decimal(str(round(multiplier, 6)))


def _realized_dividends_per_share(db: Session, player_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[float]]:
    """Per-share dividends actually paid to holders (most recent 5 per player)."""
    out: dict[uuid.UUID, list[float]] = defaultdict(list)
    if not player_ids:
        return out
    for pid, per_share in (
        db.query(DividendPayout.player_id, DividendPayout.per_share_amount)
        .filter(
            DividendPayout.player_id.in_(player_ids),
            DividendPayout.status == DividendPayoutStatus.COMPLETED,
            DividendPayout.per_share_amount.isnot(None),
        )
        .order_by(DividendPayout.created_at.desc())
        .limit(6000)
        .all()
    ):
        if len(out[pid]) < 5:
            out[pid].append(float(per_share))
    return out


def _event_signals(db: Session, player_ids: list[uuid.UUID]) -> dict[uuid.UUID, float]:
    """Dividend-timing signal from tournament entrants. + before a start (holders at start get paid), mildly - just
    after it (dividend captured)."""
    now = datetime.now(timezone.utc)
    signal: dict[uuid.UUID, float] = {}
    if not player_ids:
        return signal
    rows = (
        db.query(TournamentEntrant.player_id, Tournament.start_time)
        .join(Tournament, Tournament.id == TournamentEntrant.tournament_id)
        .filter(
            TournamentEntrant.player_id.in_(player_ids),
            Tournament.is_historical_archive.is_(False),
            Tournament.status.in_([TournamentStatus.SCHEDULED, TournamentStatus.RESULTS_PENDING]),
            Tournament.start_time.isnot(None),
            Tournament.start_time >= now - timedelta(days=2),
            Tournament.start_time <= now + timedelta(days=14),
        )
        .all()
    )
    for pid, start in rows:
        start = _aware(start)
        if start is None:
            continue
        days = (start - now).total_seconds() / 86400.0
        if days > 0:
            value = 1.0 if days <= 1 else 0.8 if days <= 3 else 0.5 if days <= 7 else 0.25
        else:
            value = -0.35  # started within the last two days: dividend already locked in
        # An upcoming event beats an ex-dividend dip if a player has both.
        if pid not in signal or value > signal[pid]:
            signal[pid] = value
    return signal


@dataclass
class MarketSnapshot:
    """Read-only per-tick bundle every bot decides against."""

    player_ids: list[uuid.UUID]
    price: dict[uuid.UUID, Decimal] = field(default_factory=dict)
    pct_change: dict[uuid.UUID, Decimal] = field(default_factory=dict)
    fair_value: dict[uuid.UUID, Decimal] = field(default_factory=dict)
    shares_outstanding: dict[uuid.UUID, int] = field(default_factory=dict)
    signals: dict[uuid.UUID, dict[str, float]] = field(default_factory=dict)
    best_recent_placement: dict[uuid.UUID, int] = field(default_factory=dict)


def _build_snapshot(db: Session) -> MarketSnapshot:
    players = db.query(Player).filter(Player.is_active.is_(True)).all()
    player_ids = [p.id for p in players]
    ipo_price_by_id = {p.id: p.ipo_price for p in players}

    history: dict[uuid.UUID, list[Decimal]] = {pid: [] for pid in player_ids}
    if player_ids:
        for row in (
            db.query(PriceSnapshot)
            .filter(PriceSnapshot.player_id.in_(player_ids))
            .order_by(PriceSnapshot.recorded_at.desc())
            .limit(max(4000, len(player_ids) * 25))
            .all()
        ):
            bucket = history.setdefault(row.player_id, [])
            if len(bucket) < 20:
                bucket.append(row.price)

    price = {pid: (history[pid][0] if history.get(pid) else ipo_price_by_id[pid]) for pid in player_ids}
    pct_change: dict[uuid.UUID, Decimal] = {}
    for pid, prices in history.items():
        if len(prices) >= 2 and prices[-1] > 0:
            pct_change[pid] = (prices[0] - prices[-1]) / prices[-1]
        else:
            pct_change[pid] = Decimal("0")

    expected_value, form = _career_stats(db, player_ids)
    ev_values = sorted(expected_value.values())
    roster_median_ev = ev_values[len(ev_values) // 2] if ev_values else None
    fair_value = {p.id: _compute_fair_value(p.ipo_price, expected_value.get(p.id), roster_median_ev) for p in players}

    # Expected dividend yield per share (net of fee), blended with what was actually paid out.
    fee = float(economic_params_service.get_param(db, "dividend.platform_fee_pct"))
    fee = fee / 100.0 if fee > 1 else fee
    realized = _realized_dividends_per_share(db, player_ids)
    yield_raw: dict[uuid.UUID, float] = {}
    for p in players:
        ev = expected_value.get(p.id)
        px = float(price[p.id])
        if ev is None or px <= 0:
            continue
        per_share = float(ev) * (1.0 - fee) / max(1, p.total_shares_outstanding)
        paid = realized.get(p.id)
        if paid:
            per_share = 0.6 * per_share + 0.4 * (sum(paid) / len(paid))
        yield_raw[p.id] = per_share / px
    positives = sorted(v for v in yield_raw.values() if v > 0)
    median_yield = positives[len(positives) // 2] if positives else None

    events = _event_signals(db, player_ids)

    signals: dict[uuid.UUID, dict[str, float]] = {}
    for p in players:
        px = float(price[p.id])
        fv = float(fair_value[p.id])
        value = _clamp(math.log(fv / px), -1.0, 1.0) if px > 0 and fv > 0 else 0.0
        y = yield_raw.get(p.id)
        if y is None or median_yield is None:
            yld = 0.0
        elif y > 0:
            yld = _clamp(math.log(y / median_yield) / 1.5, -1.0, 1.0)
        else:
            yld = -0.5
        signals[p.id] = {
            "value": value,
            "yld": yld,
            "mom": _clamp(float(pct_change.get(p.id, 0)) * 5.0, -1.0, 1.0),
            "form": form.get(p.id, 0.0),
            "event": events.get(p.id, 0.0),
        }

    return MarketSnapshot(
        player_ids=player_ids,
        price=price,
        pct_change=pct_change,
        fair_value=fair_value,
        shares_outstanding={p.id: p.total_shares_outstanding for p in players},
        signals=signals,
    )


# --- Bot population ------------------------------------------------------------------------------------------------


def _weighted_choice(rng: random.Random, weights: dict[str, float]) -> str:
    keys = list(weights.keys())
    return rng.choices(keys, weights=list(weights.values()), k=1)[0]


def _min_maker_count(n_players: int) -> int:
    return max(MM_MIN_MAKERS, math.ceil(n_players / MM_PLAYERS_PER_MAKER))


def _create_bot(db: Session, rng: random.Random, strategy: str, number: int, taken_names: set[str], starting_balance: Decimal) -> bool:
    email = f"bot-{number}@bots.forecast.internal"
    if db.query(User).filter(User.email == email).one_or_none() is not None:
        return False
    user = User(
        email=email,
        password_hash="!disabled!",  # bots never log in, same convention as the House account
        display_name=generate_username(rng, taken_names),
        role=UserRole.USER,
        is_active=True,
    )
    db.add(user)
    db.flush()
    wallet_service.get_or_create_wallet(db, user.id)
    wallet_service.deposit(db, user.id, starting_balance, memo="Bot trader starting capital")
    db.add(BotProfile(user_id=user.id, strategy=strategy, mm_player_ids=[] if strategy == "liquidity_provider" else None))
    db.flush()
    return True


def ensure_bot_population(db: Session, target_count: int, rng: random.Random) -> int:
    """Tops the population up to `target_count` and guarantees enough market makers to cover every active player
    (the maker minimum can push the total above target_count). Never removes bots. Returns how many were created."""
    n_players = db.query(func.count(Player.id)).filter(Player.is_active.is_(True)).scalar() or 0
    current = db.query(BotProfile).count()
    makers = db.query(BotProfile).filter(BotProfile.strategy == "liquidity_provider").count()
    maker_gap = max(0, _min_maker_count(n_players) - makers)
    to_create = max(0, target_count - current)
    if to_create == 0 and maker_gap == 0:
        return 0

    starting_balance = economic_params_service.get_param(db, "wallet.starting_balance")
    taken = {n.lower() for (n,) in db.query(User.display_name).all() if n}

    plan: list[str] = ["liquidity_provider"] * maker_gap
    remaining = max(0, to_create - maker_gap)
    plan += [_weighted_choice(rng, STRATEGY_WEIGHTS) for _ in range(remaining)]

    created = 0
    next_n = current
    for strategy in plan:
        for _ in range(5):  # skip numbers already taken by an earlier partial run
            next_n += 1
            if _create_bot(db, rng, strategy, next_n, taken, starting_balance):
                created += 1
                break
    return created


def _ensure_mm_coverage(db: Session, snapshot: MarketSnapshot, rng: random.Random) -> bool:
    """Every active player quoted by >= MM_COVERAGE distinct makers. Rebuilds the assignment only when something is
    off (a player uncovered, a maker with nothing, an assigned player no longer active), so quotes stay stable."""
    makers = db.query(BotProfile).filter(BotProfile.strategy == "liquidity_provider").all()
    if not makers or not snapshot.player_ids:
        return False
    active = {str(pid) for pid in snapshot.player_ids}
    cover = min(MM_COVERAGE, len(makers))

    counts: dict[str, int] = defaultdict(int)
    stale = False
    # A maker with nothing assigned only matters when there are enough slots to go round (tiny rosters can't
    # keep every maker busy, and rebuilding every tick would just churn their quotes).
    enough_slots = len(active) * cover >= len(makers)
    for m in makers:
        ids = m.mm_player_ids or []
        if not ids and enough_slots:
            stale = True
        for s in ids:
            if s in active:
                counts[s] += 1
            else:
                stale = True
    if not stale and all(counts[s] >= cover for s in active):
        return False

    players = list(active)
    rng.shuffle(players)
    assign: dict[uuid.UUID, list[str]] = {m.user_id: [] for m in makers}
    order = [m.user_id for m in makers]
    rng.shuffle(order)
    for i, pid in enumerate(players):
        for c in range(cover):
            assign[order[(i * cover + c) % len(order)]].append(pid)  # consecutive slots -> distinct makers
    for m in makers:
        m.mm_player_ids = assign[m.user_id]  # reassigned (new list) so the JSON change is detected
    return True


# --- Directional bots ---------------------------------------------------------------------------------------------


def _personality(user_id: uuid.UUID, strategy: str) -> dict:
    """Stable per-bot traits derived from its id (no schema needed): nudged signal weights, attention span, caps."""
    r = random.Random(user_id.int & 0xFFFFFFFFFFFF)
    base = SIGNAL_WEIGHTS.get(strategy, SIGNAL_WEIGHTS["random"])
    weights = {k: v * (0.75 + 0.5 * r.random()) for k, v in base.items()}
    cap = POSITION_CAP.get(strategy, POSITION_CAP["default"]) * (0.8 + 0.4 * r.random())
    return {
        "w": weights,
        "attention": r.randint(20, 60),
        "max_open": r.randint(3, 6),
        "cap": cap,
        "take_profit": TAKE_PROFIT.get(strategy, TAKE_PROFIT["default"]) * (0.8 + 0.4 * r.random()),
        "stop_loss": STOP_LOSS.get(strategy),
    }


def _base_score(snapshot: MarketSnapshot, pid: uuid.UUID, w: dict[str, float], rng: random.Random) -> float:
    sig = snapshot.signals.get(pid)
    if sig is None:
        return 0.0
    s = w["value"] * sig["value"] + w["yld"] * sig["yld"] + w["mom"] * sig["mom"] + w["form"] * sig["form"] + w["event"] * sig["event"]
    return s + rng.gauss(0.0, w["noise"] * 0.5)


def _trim_open_orders(db: Session, user_id: uuid.UUID, max_open: int) -> bool:
    """Cancels a bot's stale / excess resting orders so cash and shares don't get tied up forever."""
    open_orders = (
        db.query(Order)
        .filter(Order.user_id == user_id, Order.status.in_([OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED]))
        .order_by(Order.created_at.asc())
        .all()
    )
    now = datetime.now(timezone.utc)
    doomed = [o for o in open_orders if (c := _aware(o.created_at)) is not None and now - c > ORDER_MAX_AGE]
    keep = [o for o in open_orders if o not in doomed]
    if len(keep) > max_open:
        doomed += keep[: len(keep) - max_open]
    cancelled = False
    for order in doomed:
        try:
            order_service.cancel_order(db, user_id, order.id)
            cancelled = True
        except ServiceError:
            pass
    return cancelled


def _place(db, user_id, player_id, side: OrderSide, qty: int, ref_price: Decimal, params: dict, profile: dict, conviction: float, rng: random.Random) -> bool:
    if qty <= 0 or ref_price <= 0:
        return False
    base = float(profile["limit_prob_override"] if profile["limit_prob_override"] is not None else params["limit_order_probability"])
    limit_prob = _clamp(base - 0.25 * (conviction - 0.8), 0.05, 0.95)  # confident bots hit the market
    if rng.random() < limit_prob:
        offset = params["limit_order_offset"] * Decimal(str(round(rng.uniform(0.3, 1.6), 3)))
        factor = (Decimal("1") - offset) if side == OrderSide.BUY else (Decimal("1") + offset)
        limit_price = (ref_price * factor).quantize(Decimal("0.01"))
        if limit_price <= 0:
            return False
        order_service.place_limit_order(db, user_id, player_id, side, limit_price, qty, is_bot=True)
    else:
        order_service.place_quick_order(db, user_id, player_id, side, qty, is_bot=True)
    return True


def _run_bot_agent(db: Session, bot_user: User, profile_row: BotProfile, snapshot: MarketSnapshot, params: dict, rng: random.Random) -> bool:
    strategy = profile_row.strategy
    profile = STRATEGY_PROFILE.get(strategy, DEFAULT_PROFILE)
    if profile["skip_prob"] > 0 and rng.random() < profile["skip_prob"]:
        return False

    pers = _personality(bot_user.id, strategy)
    w = pers["w"]
    trimmed = _trim_open_orders(db, bot_user.id, pers["max_open"])

    wallet = wallet_service.get_or_create_wallet(db, bot_user.id)
    holdings = {
        pos.player_id: pos
        for pos in db.query(Position).filter(Position.user_id == bot_user.id, Position.quantity > 0).all()
        if pos.player_id in snapshot.price
    }
    held_value = sum(float(snapshot.price[pid]) * pos.quantity for pid, pos in holdings.items())
    cash = float(wallet.available_balance)
    portfolio = cash + float(getattr(wallet, "held_balance", 0) or 0) + held_value
    if portfolio <= 0:
        return trimmed
    cash_frac = cash / portfolio
    cap = pers["cap"]

    def concentration(pid: uuid.UUID) -> float:
        pos = holdings.get(pid)
        if pos is None:
            return 0.0
        return float(snapshot.price[pid]) * pos.quantity / (portfolio * cap)

    # ---- buy side: score a random watchlist
    buy_pick: tuple[float, uuid.UUID] | None = None
    if cash_frac > MIN_CASH_FRACTION and snapshot.player_ids:
        watch = rng.sample(snapshot.player_ids, k=min(len(snapshot.player_ids), pers["attention"]))
        scored = []
        for pid in watch:
            if snapshot.price.get(pid, Decimal("0")) <= 0:
                continue
            conc = concentration(pid)
            if conc >= 1.0:
                continue  # already at this bot's position cap
            scored.append((_base_score(snapshot, pid, w, rng) - w["conc"] * conc, pid))
        scored.sort(key=lambda t: t[0], reverse=True)
        top = scored[:5]
        if top and top[0][0] >= BUY_FLOOR:
            buy_pick = rng.choices(top, weights=[math.exp(_clamp(2 * s, -6, 6)) for s, _ in top], k=1)[0]

    # ---- sell side: re-score everything held
    sell_pick: tuple[float, uuid.UUID] | None = None
    sells = []
    for pid, pos in holdings.items():
        if pos.available_quantity <= 0:
            continue
        s = -_base_score(snapshot, pid, w, rng) + w["conc"] * max(0.0, concentration(pid) - 0.6)
        avg_cost = float(pos.average_cost or 0)
        px = float(snapshot.price[pid])
        if avg_cost > 0:
            pnl = px / avg_cost - 1.0
            if pnl > pers["take_profit"]:
                s += 0.5 + min(0.5, pnl - pers["take_profit"])
            if pers["stop_loss"] is not None and pnl < pers["stop_loss"]:
                s += 0.7
        sells.append((s, pid))
    sells.sort(key=lambda t: t[0], reverse=True)
    if sells and sells[0][0] >= SELL_FLOOR:
        sell_pick = sells[0]

    if buy_pick is None and sell_pick is None:
        return trimmed

    if buy_pick is not None and sell_pick is not None:
        p_buy = _clamp(0.25 + 0.7 * cash_frac, 0.15, 0.9)  # idle cash pushes toward buying
        do_buy = rng.random() < p_buy
    else:
        do_buy = buy_pick is not None

    if do_buy:
        score, pid = buy_pick  # type: ignore[misc]
        price = snapshot.price[pid]
        conviction = _clamp(0.5 + score, 0.4, 1.6)
        dampener = Decimal(str(round(rng.uniform(0.3, 1.0), 4)))
        spend = wallet.available_balance * params["max_trade_cash_fraction"] * profile["size_mult"] * dampener * Decimal(str(round(conviction, 3)))
        room = Decimal(str(max(0.0, cap * portfolio - (float(price) * holdings[pid].quantity if pid in holdings else 0.0))))
        spend = min(spend, wallet.available_balance, room)
        qty = int(spend // price)
        return _place(db, bot_user.id, pid, OrderSide.BUY, qty, price, params, profile, conviction, rng) or trimmed

    score, pid = sell_pick  # type: ignore[misc]
    have = holdings[pid].available_quantity
    conviction = _clamp(score, 0.4, 1.6)
    dampener = Decimal(str(round(rng.uniform(0.4, 1.0), 4)))
    frac = min(Decimal("1"), params["max_trade_share_fraction"] * profile["size_mult"] * dampener * Decimal(str(round(conviction, 3))))
    qty = min(have, max(1, int(have * frac)))
    return _place(db, bot_user.id, pid, OrderSide.SELL, qty, snapshot.price[pid], params, profile, conviction, rng) or trimmed


# --- Market makers ------------------------------------------------------------------------------------------------


def _run_liquidity_provider(db: Session, bot_user: User, profile_row: BotProfile, snapshot: MarketSnapshot, params: dict, rng: random.Random) -> bool:
    assigned = [uuid.UUID(s) for s in (profile_row.mm_player_ids or [])]
    if not assigned:
        return False
    assigned_set = set(assigned)

    open_orders = (
        db.query(Order)
        .filter(Order.user_id == bot_user.id, Order.status.in_([OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED]))
        .all()
    )
    by_player: dict[uuid.UUID, list[Order]] = defaultdict(list)
    for o in open_orders:
        by_player[o.player_id].append(o)

    acted = False
    # Quotes on players this maker no longer covers (assignment was rebalanced) are pulled.
    for pid, orders in list(by_player.items()):
        if pid not in assigned_set:
            for o in orders:
                try:
                    order_service.cancel_order(db, bot_user.id, o.id)
                    acted = True
                except ServiceError:
                    pass

    # Players with no quotes at all go first, then the rest in random order.
    rng.shuffle(assigned)
    assigned.sort(key=lambda pid: 1 if by_player.get(pid) else 0)
    targets = assigned[:MM_PLAYERS_PER_TICK]

    for pid in targets:
        price = snapshot.price.get(pid)
        if not price or price <= 0:
            continue
        fair = snapshot.fair_value.get(pid) or price
        skew = _clamp(math.log(float(fair) / float(price)), -MM_MAX_SKEW, MM_MAX_SKEW) if fair > 0 else 0.0
        mid = price * Decimal(str(round(1 + skew, 6)))
        vol = abs(float(snapshot.pct_change.get(pid, 0)))
        spread = params["mm_spread_offset"] * Decimal(str(round(1 + min(2.0, vol * 8), 4)))
        bid = (mid * (Decimal("1") - spread)).quantize(Decimal("0.01"))
        ask = (mid * (Decimal("1") + spread)).quantize(Decimal("0.01"))
        if bid <= 0 or ask <= bid:
            continue

        existing = by_player.get(pid, [])
        position = db.query(Position).filter(Position.user_id == bot_user.id, Position.player_id == pid).one_or_none()
        have = position.available_quantity if position is not None else 0

        tol = price * spread * Decimal("0.5")
        bid_ok = any(o.side == OrderSide.BUY and o.limit_price is not None and abs(o.limit_price - bid) <= tol for o in existing)
        ask_ok = any(o.side == OrderSide.SELL and o.limit_price is not None and abs(o.limit_price - ask) <= tol for o in existing)
        if bid_ok and (ask_ok or have == 0):
            continue  # quotes still fresh

        for order in existing:
            try:
                order_service.cancel_order(db, bot_user.id, order.id)
                acted = True
            except ServiceError:
                pass

        wallet = wallet_service.get_or_create_wallet(db, bot_user.id)
        quote_fraction = params["mm_quote_size_fraction"]
        max_qty = max(1, snapshot.shares_outstanding.get(pid, 10_000) // 100)

        qty = min(int((wallet.available_balance * quote_fraction) // bid), max_qty)
        if qty > 0:
            try:
                order_service.place_limit_order(db, bot_user.id, pid, OrderSide.BUY, bid, qty, is_bot=True)
                acted = True
            except ServiceError:
                pass

        position = db.query(Position).filter(Position.user_id == bot_user.id, Position.player_id == pid).one_or_none()
        have = position.available_quantity if position is not None else 0
        if have > 0:
            ask_qty = min(have, max(1, int(have * quote_fraction * 4)), max_qty)
            try:
                order_service.place_limit_order(db, bot_user.id, pid, OrderSide.SELL, ask, ask_qty, is_bot=True)
                acted = True
            except ServiceError:
                pass

    return acted


# --- Tick -----------------------------------------------------------------------------------------------------------


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
    """One full tick: top up the population, make sure every player has market-maker coverage, let a random subset of
    directional bots act, and let (most) market makers refresh quotes. Commits per bot so one failure can't roll back
    another's success. Safe to call repeatedly (background loop in app/main.py, POST /admin/bots/tick, or
    scripts/kickstart_market.py)."""
    rng = rng or random.Random()
    params = _load_params(db)

    ensure_bot_population(db, int(params["population_size"]), rng)
    db.commit()

    bots = db.query(BotProfile).all()
    if not bots:
        return {"population": 0, "active": 0, "actions": 0, "errors": 0}

    snapshot = _build_snapshot(db)
    if _ensure_mm_coverage(db, snapshot, rng):
        db.commit()

    makers = [b for b in bots if b.strategy == "liquidity_provider"]
    agents = [b for b in bots if b.strategy != "liquidity_provider"]
    n_active = max(1, int(len(agents) * float(params["participation_rate"]))) if agents else 0
    active = rng.sample(agents, k=min(n_active, len(agents))) + [m for m in makers if rng.random() < 0.8]

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
