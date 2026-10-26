"""
Bot trading population -- an agent-based market. Each bot is an independent investor with its own opinion of what every
pro's stock is worth; the prices you see are what comes out of those opinions meeting each other (and real users) on the
order book. Every order goes through the same order_service functions a human's click would.

How a bot forms a valuation
---------------------------
A shared, data-driven MODEL VALUE per player is built every tick from live data:
  * fair value  -- IPO price scaled by career-long expected dividends (every past placement is run through the real
                   payout curve against that tournament's field size and pool, recency-weighted, normalized to the roster);
  * outlook     -- recent form (last 3 results vs career), plus the dividend calendar: a player entered in an event that
                   starts soon is worth more (holders at the START are paid; the bump is the expected per-share dividend),
                   and right after the start the dividend is "captured" so value dips (ex-dividend).
Each bot then turns that into ITS OWN value: it blends the model with the recent market price (how much it trusts the
crowd), applies a persistent personal "belief" that drifts slowly over hours (so bots disagree, and disagreements change),
and tilts by style (momentum chasers, contrarians, dividend hunters ...). Team-change news is not a data source we have,
so beliefs are the stand-in for the real-world noise of rumours and roster moves.

How a bot trades
----------------
  * Budget aware: it targets a cash level (its style's comfort zone). Too much idle cash makes it value stocks a little
    higher (it wants to deploy); too little makes it value them lower (it wants to raise cash). Position size is capped
    per player and per order, from its actual balance.
  * Takes when price crosses its value: buys when the price is below its value by more than its required margin, sells
    when above, with conviction deciding limit vs. instant and size.
  * Rests when it doesn't want the current price: it posts a bid below and an ask above its value (refreshing them as its
    value moves), so the order book always has strategic depth even when nobody trades.
  * Attention follows popularity: each tick a bot looks at a watchlist sampled in proportion to a player's popularity
    (market cap, upcoming events, form), so busy stocks trade more and obscure ones still trade occasionally. A per-tick
    cap on aggressive orders keeps the whole economy lively but not frantic.

Market makers (strategy "liquidity_provider") are assigned so EVERY active player is quoted by at least MM_COVERAGE makers.
"""
from __future__ import annotations

import math
import random
import time
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
from app.services import economic_params_service, order_service, qualifier_model_service, wallet_service
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

# Per-archetype personality centres. sigma = how far its beliefs wander from the model (log scale); anchor = weight on
# the recent market price vs the model; margin = edge it demands before taking; tilt_mom / tilt_event = style tilts;
# cash = the cash fraction it is comfortable holding.
STYLE: dict[str, dict[str, float]] = {
    "momentum_trader": dict(sigma=0.09, anchor=0.50, margin=0.020, tilt_mom=0.05, tilt_event=0.01, cash=0.20),
    "contrarian": dict(sigma=0.10, anchor=0.15, margin=0.035, tilt_mom=-0.04, tilt_event=0.00, cash=0.30),
    "value_investor": dict(sigma=0.07, anchor=0.15, margin=0.050, tilt_mom=0.00, tilt_event=0.01, cash=0.25),
    "dividend_hunter": dict(sigma=0.08, anchor=0.30, margin=0.030, tilt_mom=0.01, tilt_event=0.04, cash=0.15),
    "whale": dict(sigma=0.06, anchor=0.25, margin=0.030, tilt_mom=0.01, tilt_event=0.02, cash=0.10),
    "scalper": dict(sigma=0.05, anchor=0.60, margin=0.010, tilt_mom=0.03, tilt_event=0.00, cash=0.35),
    "panic_seller": dict(sigma=0.12, anchor=0.40, margin=0.020, tilt_mom=0.06, tilt_event=0.00, cash=0.40),
    "index_investor": dict(sigma=0.04, anchor=0.50, margin=0.030, tilt_mom=0.00, tilt_event=0.00, cash=0.05),
    "random": dict(sigma=0.15, anchor=0.30, margin=0.030, tilt_mom=0.00, tilt_event=0.00, cash=0.30),
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

POSITION_CAP = {"whale": 0.30, "index_investor": 0.05, "scalper": 0.08, "dividend_hunter": 0.20, "default": 0.15}

MIN_CASH_FRACTION = 0.03
REST_PER_TICK = 2            # strategic resting-order refreshes per bot per tick
TAKER_BUDGET_FRACTION = 0.06  # aggressive orders per tick across the whole population, as a fraction of the bots acting
BELIEF_EPOCH_SECONDS = 6 * 3600  # a bot's private beliefs drift (interpolated) over this period

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


def _career_stats(
    db: Session, player_ids: list[uuid.UUID]
) -> tuple[dict[uuid.UUID, Decimal], dict[uuid.UUID, float], dict[uuid.UUID, float], dict[uuid.UUID, float]]:
    """Returns (expected_value, form, career_fraction, career_strength) per player.

    career_fraction: recency-weighted average payout-curve fraction (what an event typically pays them).
    career_strength: recency-weighted average finish strength 0..1 (1 = won) -- used as the team prior for qualifiers.

    expected_value: recency-weighted average of what each past placement was worth as a dividend pool (placement run
    through the real payout curve against that tournament's own field size and pool). Missing = no history.
    form: recent (last 3) placement-curve fraction versus the player's own career average, clamped to -1..+1.
    Results are ordered by TOURNAMENT START TIME (not row-creation time), so a bulk historical backfill still reads
    in true chronological order."""
    if not player_ids:
        return {}, {}, {}, {}

    rows = (
        db.query(PlacementResult.player_id, PlacementResult.tournament_id, PlacementResult.placement)
        .join(Tournament, Tournament.id == PlacementResult.tournament_id)
        .filter(PlacementResult.player_id.in_(player_ids))
        .order_by(Tournament.start_time.desc().nullslast(), PlacementResult.created_at.desc())
        .limit(30000)
        .all()
    )
    if not rows:
        return {}, {}, {}, {}

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
    career_fraction: dict[uuid.UUID, float] = {}
    career_strength: dict[uuid.UUID, float] = {}
    for player_id, results in by_player.items():
        recent = results[:HISTORY_MAX_RESULTS_PER_PLAYER]  # most-recent-first
        weighted_sum = Decimal("0")
        weight_total = Decimal("0")
        fractions: list[float] = []
        strengths: list[tuple[float, float]] = []
        for rank, (tournament_id, placement) in enumerate(recent):
            max_placement = max(1, field_size.get(tournament_id, 1))
            fraction = placement_payout_fraction(placement, max_placement, curve)
            weight = decay**rank
            weighted_sum += pools.get(tournament_id, Decimal("0")) * fraction * weight
            weight_total += weight
            fractions.append(float(fraction))
            strengths.append((float(decay**rank), 1.0 - (placement - 1) / max(1, max_placement - 1)))
        if weight_total > 0:
            expected_value[player_id] = weighted_sum / weight_total
        if len(fractions) >= 2:
            recent_avg = sum(fractions[:3]) / len(fractions[:3])
            career_avg = sum(fractions) / len(fractions)
            form[player_id] = _clamp((recent_avg - career_avg) / max(career_avg, 1e-9), -1.0, 1.0)
        if fractions:
            career_fraction[player_id] = sum(fractions) / len(fractions)
        if strengths:
            career_strength[player_id] = _clamp(sum(w * v for w, v in strengths) / sum(w for w, _ in strengths), 0.0, 1.0)
    return expected_value, form, career_fraction, career_strength


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
    # fair value adjusted for outlook (form + dividend calendar): the shared "model" every bot starts from
    model_value: dict[uuid.UUID, Decimal] = field(default_factory=dict)
    ref_price: dict[uuid.UUID, Decimal] = field(default_factory=dict)  # recent average trade price
    popularity: dict[uuid.UUID, float] = field(default_factory=dict)   # attention weight (>0)
    shares_outstanding: dict[uuid.UUID, int] = field(default_factory=dict)
    signals: dict[uuid.UUID, dict[str, float]] = field(default_factory=dict)
    qual_view: dict[uuid.UUID, object] = field(default_factory=dict)  # QualifierView per player with earlier-round data
    # The qualifier part of the outlook (log scale) already inside model_value, kept separate so each bot can weigh it differently.
    qual_out: dict[uuid.UUID, float] = field(default_factory=dict)
    qual_uncertainty: dict[uuid.UUID, float] = field(default_factory=dict)
    movers: list = field(default_factory=list)  # players the whole market is looking at right now (big moves / news)
    best_recent_placement: dict[uuid.UUID, int] = field(default_factory=dict)


def _find_movers(pct_change, signals, qviews) -> list:
    """Players every watcher notices at once: the biggest recent price moves, plus anyone whose qualifier standing
    just made them a clear winner or loser. Ordered by how loud the news is."""
    scored: list[tuple[float, uuid.UUID]] = []
    for pid, sig in signals.items():
        loud = abs(float(pct_change.get(pid, 0)))
        qv = qviews.get(pid)
        if qv is not None and qv.status in ("qualified", "eliminated"):
            loud += 0.03 + 0.04 * abs(qv.perf_ratio - 1.0)
        if loud >= 0.03:
            scored.append((loud, pid))
    scored.sort(reverse=True)
    return [pid for _, pid in scored[:25]]


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
    ref_price = {
        pid: (sum(history[pid], Decimal("0")) / len(history[pid]) if history.get(pid) else ipo_price_by_id[pid])
        for pid in player_ids
    }
    pct_change: dict[uuid.UUID, Decimal] = {}
    for pid, prices in history.items():
        if len(prices) >= 2 and prices[-1] > 0:
            pct_change[pid] = (prices[0] - prices[-1]) / prices[-1]
        else:
            pct_change[pid] = Decimal("0")

    expected_value, form, career_fraction, career_strength = _career_stats(db, player_ids)
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
    qviews = qualifier_model_service.build_views(db, player_ids, career_fraction, career_strength)
    # A qualifier-derived event time overrides the calendar signal when the player has no entrant row yet
    for pid, qv in qviews.items():
        if pid in events or qv.event_start is None or qv.status == "eliminated":
            continue
        days = (qv.event_start - datetime.now(timezone.utc)).total_seconds() / 86400.0
        if days > 0:
            events[pid] = (1.0 if days <= 1 else 0.8 if days <= 3 else 0.5 if days <= 7 else 0.25) * max(0.3, qv.p_qualify)

    qual_out: dict[uuid.UUID, float] = {}
    signals: dict[uuid.UUID, dict[str, float]] = {}
    model_value: dict[uuid.UUID, Decimal] = {}
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
        ev_sig = events.get(p.id, 0.0)
        fm = form.get(p.id, 0.0)
        signals[p.id] = {
            "value": value,
            "yld": yld,
            "mom": _clamp(float(pct_change.get(p.id, 0)) * 5.0, -1.0, 1.0),
            "form": fm,
            "event": ev_sig,
            "qual": (qviews[p.id].perf_ratio - 1.0) if p.id in qviews else 0.0,
        }
        # Outlook: form, plus the dividend calendar -- the expected per-share dividend is a price bump before a start
        # and drops out right after it (ex-dividend).
        out = 0.08 * fm
        qv = qviews.get(p.id)
        if qv is not None:
            # Earlier rounds: expected payout from the coming Finals vs what this player usually earns.
            # Strong qualifier -> bump; missed the cut / weak -> markdown. Scaled by how sure the estimate is.
            q_out = _clamp(0.12 * (qv.perf_ratio - 1.0) * (1.0 - 0.5 * qv.uncertainty), -0.18, 0.12)
            qual_out[p.id] = q_out
            out += q_out
        yy = max(0.0, yield_raw.get(p.id, 0.0))
        if ev_sig > 0:
            out += min(0.15, yy * ev_sig)
        elif ev_sig < 0:
            out -= min(0.10, yy * 0.7)
        out = _clamp(out, -0.20, 0.25)
        model_value[p.id] = fair_value[p.id] * Decimal(str(round(math.exp(out), 6)))

    # Popularity: market-cap rank (sub-linear), boosted by an imminent event and by big form swings / verified pros.
    caps = {p.id: float(price[p.id]) * p.total_shares_outstanding for p in players}
    cap_sorted = sorted(caps.values())
    median_cap = cap_sorted[len(cap_sorted) // 2] if cap_sorted else 1.0
    popularity: dict[uuid.UUID, float] = {}
    for p in players:
        w = (caps[p.id] / median_cap) ** 0.6 if median_cap > 0 and caps[p.id] > 0 else 0.2
        w *= 1.0 + 1.5 * max(0.0, events.get(p.id, 0.0)) + 0.5 * abs(form.get(p.id, 0.0))
        if p.is_verified:
            w *= 1.2
        popularity[p.id] = _clamp(w, 0.1, 12.0)

    return MarketSnapshot(
        player_ids=player_ids,
        price=price,
        pct_change=pct_change,
        fair_value=fair_value,
        model_value=model_value,
        ref_price=ref_price,
        popularity=popularity,
        shares_outstanding={p.id: p.total_shares_outstanding for p in players},
        signals=signals,
        qual_view=qviews,
        qual_out=qual_out,
        qual_uncertainty={pid: qv.uncertainty for pid, qv in qviews.items()},
        movers=_find_movers(pct_change, signals, qviews),
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
    # Bankrolls vary like a real player base (a few big wallets, a lot of small ones): log-normal around the standard
    # starting balance, so the leaderboard doesn't open as a wall of identical numbers.
    bankroll = (starting_balance * Decimal(str(round(_clamp(math.exp(random.Random(user.id.int).gauss(0.0, 0.55)), 0.3, 5.0), 3)))).quantize(Decimal("1"))
    wallet_service.deposit(db, user.id, bankroll, memo="Bot trader starting capital")
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
    """Stable per-bot traits derived from its id (no schema needed)."""
    r = random.Random(user_id.int & 0xFFFFFFFFFFFF)
    s = STYLE.get(strategy, STYLE["random"])
    return {
        "sigma": s["sigma"] * (0.8 + 0.4 * r.random()),
        "anchor": _clamp(s["anchor"] + r.uniform(-0.1, 0.1), 0.05, 0.8),
        "margin": s["margin"] * (0.8 + 0.45 * r.random()),
        "tilt_mom": s["tilt_mom"],
        "tilt_event": s["tilt_event"],
        "target_cash": _clamp(s["cash"] + r.uniform(-0.08, 0.08), 0.02, 0.6),
        # How much weight this bot gives the qualifier evidence (some ignore it, some over-read it), and how much it
        # misreads uncertain situations -- this is what makes bots disagree about the same player.
        "info_qual": _clamp(r.gauss(1.0, 0.45), 0.1, 2.0),
        "info_noise": r.uniform(0.4, 1.6),
        "attention": r.randint(8, 16),
        "max_open": r.randint(5, 12),
        "max_takes": r.randint(1, 2),
        "cap": POSITION_CAP.get(strategy, POSITION_CAP["default"]) * (0.8 + 0.4 * r.random()),
    }


def _belief_z(user_id: uuid.UUID, pid: uuid.UUID, epoch: int) -> float:
    seed = (user_id.int ^ (pid.int * 2654435761) ^ (epoch * 1000003)) & 0xFFFFFFFFFFFFFFFF
    return random.Random(seed).gauss(0.0, 1.0)


def _bot_value(snapshot: MarketSnapshot, pid: uuid.UUID, pers: dict, user_id: uuid.UUID, now_ts: float) -> float | None:
    """This bot's private estimate of one stock's worth right now."""
    model = snapshot.model_value.get(pid)
    ref = snapshot.ref_price.get(pid)
    if not model or not ref or model <= 0 or ref <= 0:
        return None
    h = pers["anchor"]
    base = math.exp((1.0 - h) * math.log(float(model)) + h * math.log(float(ref)))
    # Belief drifts smoothly: interpolate between this epoch's draw and the next.
    pos = now_ts / BELIEF_EPOCH_SECONDS
    epoch = int(pos)
    frac = pos - epoch
    z = (1.0 - frac) * _belief_z(user_id, pid, epoch) + frac * _belief_z(user_id, pid, epoch + 1)
    # Uncertain players (few rounds played, event far off) get more disagreement between bots.
    unc = snapshot.qual_uncertainty.get(pid, 0.0)
    belief = math.exp(pers["sigma"] * (1.0 + 0.8 * unc) * z)
    # Qualifier evidence: each bot weighs it differently and reads it with its own (slowly changing) noise.
    q_out = snapshot.qual_out.get(pid)
    if q_out:
        zq = (1.0 - frac) * _belief_z(user_id, pid, epoch + 7919) + frac * _belief_z(user_id, pid, epoch + 7920)
        weight = pers["info_qual"] * (1.0 + 0.35 * pers["info_noise"] * unc * zq)
        base *= math.exp(q_out * (weight - 1.0))
    sig = snapshot.signals.get(pid, {})
    tilt = 1.0 + pers["tilt_mom"] * sig.get("mom", 0.0) + pers["tilt_event"] * max(0.0, sig.get("event", 0.0))
    return max(0.01, base * belief * tilt)


def _weighted_sample(rng: random.Random, items: list, weights: list[float], k: int) -> list:
    """k distinct items drawn with probability proportional to weight (Efraimidis-Spirakis)."""
    if k >= len(items):
        return list(items)
    keyed = sorted(((rng.random() ** (1.0 / max(w, 1e-9)), it) for it, w in zip(items, weights)), reverse=True)
    return [it for _, it in keyed[:k]]


def _trim_open_orders(db: Session, user_id: uuid.UUID, orders: list[Order], max_open: int) -> set:
    """Cancels stale / excess resting orders (oldest first) so cash and shares don't stay tied up. Returns the ids
    that were cancelled."""
    now = datetime.now(timezone.utc)
    ordered = sorted(orders, key=lambda o: _aware(o.created_at) or now)
    doomed = [o for o in ordered if (c := _aware(o.created_at)) is not None and now - c > ORDER_MAX_AGE]
    keep = [o for o in ordered if o not in doomed]
    if len(keep) > max_open:
        doomed += keep[: len(keep) - max_open]
    cancelled: set = set()
    for order in doomed:
        try:
            order_service.cancel_order(db, user_id, order.id)
            cancelled.add(order.id)
        except ServiceError:
            pass
    return cancelled


def _submit(db, user_id, pid, side: OrderSide, qty: int, limit_price: float | None) -> bool:
    """A limit order at `limit_price`, or an instant (quick) order when it is None."""
    if qty <= 0:
        return False
    if limit_price is None:
        order_service.place_quick_order(db, user_id, pid, side, qty, is_bot=True)
        return True
    lp = Decimal(str(round(limit_price, 2)))
    if lp < Decimal("0.01"):
        return False
    order_service.place_limit_order(db, user_id, pid, side, lp, qty, is_bot=True)
    return True


def _run_bot_agent(db: Session, bot_user: User, profile_row: BotProfile, snapshot: MarketSnapshot, params: dict, rng: random.Random, budget: dict) -> bool:
    strategy = profile_row.strategy
    profile = STRATEGY_PROFILE.get(strategy, DEFAULT_PROFILE)
    if profile["skip_prob"] > 0 and rng.random() < profile["skip_prob"]:
        return False

    pers = _personality(bot_user.id, strategy)
    size_mult = float(profile["size_mult"])
    cash_fraction_cap = float(params["max_trade_cash_fraction"])
    share_fraction_cap = float(params["max_trade_share_fraction"])

    open_orders = (
        db.query(Order)
        .filter(Order.user_id == bot_user.id, Order.status.in_([OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED]))
        .all()
    )
    cancelled = _trim_open_orders(db, bot_user.id, open_orders, pers["max_open"])
    acted = bool(cancelled)
    by_player: dict[uuid.UUID, list[Order]] = defaultdict(list)
    for o in open_orders:
        if o.id not in cancelled:
            by_player[o.player_id].append(o)

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
        return acted
    cap = pers["cap"]

    # Budget awareness: more cash than it wants to hold -> values stocks a bit higher (deploy); less -> lower (raise cash).
    eager = _clamp((cash / portfolio - pers["target_cash"]) / 0.3, -1.0, 1.0)
    now_ts = time.time()

    # Watchlist: popularity-weighted sample of the market, plus a few of its own holdings.
    pool = snapshot.player_ids
    if not pool:
        return acted
    watch = _weighted_sample(rng, pool, [snapshot.popularity.get(p, 1.0) for p in pool], pers["attention"])
    held_ids = list(holdings.keys())
    # Constant watching: every tick the bot reviews ALL of its holdings and whatever the market is reacting to.
    for pid in held_ids:
        if pid not in watch:
            watch.append(pid)
    alerts = [pid for pid in snapshot.movers if pid not in watch]
    for pid in rng.sample(alerts, min(len(alerts), 2 + pers["attention"] // 6)):
        watch.append(pid)

    opps = []
    for pid in watch:
        px = float(snapshot.price.get(pid, 0))
        if px <= 0:
            continue
        v = _bot_value(snapshot, pid, pers, bot_user.id, now_ts)
        if v is None:
            continue
        opps.append((pid, px, v * (1.0 + 0.04 * eager), pers["margin"]))

    def position_room(pid: uuid.UUID, px: float) -> float:
        pos = holdings.get(pid)
        have_value = px * pos.quantity if pos is not None else 0.0
        return max(0.0, cap * portfolio - have_value)

    # ---- 1) Take: the price has crossed this bot's value by more than its required margin.
    handled: set = set()
    takes = 0
    for pid, px, v, m in sorted(opps, key=lambda o: abs(math.log(o[2] / o[1])), reverse=True):
        if takes >= pers["max_takes"] or budget["takes"] <= 0:
            break
        pos = holdings.get(pid)
        buy_edge = v / px - 1.0 - m
        sell_edge = px / v - 1.0 - m
        conviction = _clamp((max(buy_edge, sell_edge)) / (3.0 * m) + 0.35, 0.35, 0.95)
        if max(buy_edge, sell_edge) <= 0 or rng.random() > conviction:
            continue
        dampener = rng.uniform(0.3, 1.0)
        instant = rng.random() < 0.25 * conviction
        try:
            if buy_edge > 0 and cash / portfolio > MIN_CASH_FRACTION:
                spend = min(cash * cash_fraction_cap * size_mult * dampener * (0.6 + conviction), position_room(pid, px))
                limit = min(v * (1.0 - m * 0.5), px * 1.02)
                qty = int(spend // max(limit, 0.01))
                if _submit(db, bot_user.id, pid, OrderSide.BUY, qty, None if instant else limit):
                    cash -= qty * limit
                    acted = True
                    takes += 1
                    budget["takes"] -= 1
                    handled.add(pid)
            elif sell_edge > 0 and pos is not None and pos.available_quantity > 0:
                frac = min(1.0, share_fraction_cap * size_mult * dampener * (0.6 + conviction))
                qty = min(pos.available_quantity, max(1, int(pos.available_quantity * frac)))
                limit = max(v * (1.0 + m * 0.5), px * 0.98)
                if _submit(db, bot_user.id, pid, OrderSide.SELL, qty, None if instant else limit):
                    acted = True
                    takes += 1
                    budget["takes"] -= 1
                    handled.add(pid)
        except (ServiceError, ValueError):
            continue

    # ---- 2) Rest: strategic orders at its own value band, even when it doesn't want to trade at today's price.
    rests = 0
    for pid, px, v, m in opps:
        if rests >= REST_PER_TICK:
            break
        if pid in handled:
            continue
        bid = min(v * (1.0 - m), px * 0.998)
        ask = max(v * (1.0 + m), px * 1.002)
        if not (0.7 * px <= bid):
            bid = 0.0
        if not (ask <= 1.45 * px):
            ask = 0.0
        pos = holdings.get(pid)
        can_ask = ask > 0 and pos is not None and pos.available_quantity > 0
        can_bid = bid > 0 and cash / portfolio > MIN_CASH_FRACTION and position_room(pid, px) > bid

        existing = by_player.get(pid, [])
        has_bid = any(o.side == OrderSide.BUY and o.limit_price is not None and abs(float(o.limit_price) - bid) <= 0.03 * bid for o in existing) if bid else True
        has_ask = any(o.side == OrderSide.SELL and o.limit_price is not None and abs(float(o.limit_price) - ask) <= 0.03 * ask for o in existing) if ask else True
        need_bid = can_bid and not has_bid
        need_ask = can_ask and not has_ask
        if not (need_bid or need_ask):
            continue
        try:
            # Replace this bot's stale quotes on the player before posting fresh ones.
            for o in existing:
                if (o.side == OrderSide.BUY and need_bid) or (o.side == OrderSide.SELL and need_ask):
                    order_service.cancel_order(db, bot_user.id, o.id)
                    acted = True
            if need_bid:
                spend = min(cash * cash_fraction_cap * 0.5 * size_mult * rng.uniform(0.4, 1.0), position_room(pid, px))
                qty = int(spend // max(bid, 0.01))
                if _submit(db, bot_user.id, pid, OrderSide.BUY, qty, bid):
                    cash -= qty * bid
                    acted = True
            if need_ask and pos is not None:
                qty = min(pos.available_quantity, max(1, int(pos.available_quantity * rng.uniform(0.2, 0.5))))
                if _submit(db, bot_user.id, pid, OrderSide.SELL, qty, ask):
                    acted = True
            rests += 1
        except (ServiceError, ValueError):
            continue

    return acted


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
        fair = snapshot.model_value.get(pid) or price
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
    rng.shuffle(active)
    # Caps how many aggressive (taking) orders the whole population fires this tick: lively, not frantic.
    budget = {"takes": max(2, round(TAKER_BUDGET_FRACTION * max(1, len(agents))))}

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
                acted = _run_bot_agent(db, bot_user, profile_row, snapshot, params, rng, budget)
            if acted:
                db.commit()
                actions += 1
            else:
                db.rollback()
        except (ServiceError, ValueError):
            db.rollback()
            errors += 1

    return {"population": len(bots), "active": len(active), "actions": actions, "errors": errors}
