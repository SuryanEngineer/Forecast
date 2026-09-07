"""
Models new HUMAN users joining Forecast after the initial auction. Bots
are a separate, fixed, permanent population (see population.py) and never
enter through this path -- only humans grow over the season, spec: 50 ->
200 across the run (`human_entrant_growth_target` additional humans,
default 150).

Growth is PACED rather than open-ended: the per-round join probability is
calibrated so the expected total number of new humans by the end of the
season lands on `human_entrant_growth_target`, and a hard cap prevents
overshoot. Each new entrant shows up with a fresh cash balance
(`new_entrant_cash`, "the starting income") and immediately deploys a
chunk of it via its assigned strategy's own buy logic -- reusing the
exact same strategy code used for ongoing trading, so a new smart_money
entrant looks for undervalued players on day one, a new hype_chaser buys
hype, etc.
"""

from itertools import count
import numpy as np

from .config import SimConfig
from .models import User
from .strategies import pick_buy_targets

_new_user_ids = None  # initialized per-Simulator via init_id_counter


def init_id_counter(start_at: int):
    global _new_user_ids
    _new_user_ids = count(start_at)


def _weighted_choice(rng: np.random.Generator, weights: dict) -> str:
    keys = list(weights.keys())
    probs = np.array(list(weights.values()), dtype=float)
    probs = probs / probs.sum()
    return rng.choice(keys, p=probs)


def join_pacing(cfg: SimConfig):
    """Calibrated so E[total new humans over the season] ~= growth target,
    given the batch size range and total number of trading rounds. Returns
    (join_prob, batch_scale): if the growth target is large enough that
    even joining every single round wouldn't hit it with the configured
    min/max batch size, batch_scale > 1 widens the batch instead of
    silently under-delivering the requested growth target."""
    total_rounds = max(1, cfg.num_tournaments * cfg.trading_rounds_per_tournament)
    avg_batch = (cfg.new_entrants_min + cfg.new_entrants_max) / 2.0
    if avg_batch <= 0 or cfg.human_entrant_growth_target <= 0:
        return 0.0, 1.0
    needed_per_round = cfg.human_entrant_growth_target / total_rounds
    if needed_per_round <= avg_batch:
        return needed_per_round / avg_batch, 1.0
    return 1.0, needed_per_round / avg_batch


def per_round_join_probability(cfg: SimConfig) -> float:
    """Back-compat wrapper -- prefer join_pacing() which also returns the
    batch_scale needed for large growth targets."""
    prob, _ = join_pacing(cfg)
    return prob


def maybe_spawn_new_users(users, users_by_id, cfg: SimConfig, rng: np.random.Generator,
                           tournament_idx: int, num_human_entrants_so_far: int,
                           join_prob: float, batch_scale: float = 1.0):
    """Returns (list of newly-created User objects [already appended to
    users/users_by_id], updated num_human_entrants_so_far)."""
    if not cfg.enable_new_entrants:
        return [], num_human_entrants_so_far
    remaining_target = cfg.human_entrant_growth_target - num_human_entrants_so_far
    if remaining_target <= 0:
        return [], num_human_entrants_so_far
    if rng.random() >= join_prob:
        return [], num_human_entrants_so_far

    lo = max(1, int(round(cfg.new_entrants_min * batch_scale)))
    hi = max(lo, int(round(cfg.new_entrants_max * batch_scale)))
    n_new = int(rng.integers(lo, hi + 1))
    n_new = min(n_new, remaining_target)
    new_users = []
    for _ in range(n_new):
        uid = next(_new_user_ids)
        strategy = _weighted_choice(rng, cfg.trading_strategy_weights)
        cash = cfg.new_entrant_cash
        if rng.random() < cfg.new_entrant_whale_prob:
            cash *= cfg.new_entrant_whale_cash_multiplier
        user = User(
            user_id=uid,
            name=f"entrant_{uid}",
            cash=cash,
            strategy=strategy,
            joined_tournament=tournament_idx,
            is_bot=False,
        )
        users.append(user)
        users_by_id[uid] = user
        new_users.append(user)
    return new_users, num_human_entrants_so_far + len(new_users)


def onboard_new_user(user: User, market, snap, cfg: SimConfig, rng: np.random.Generator, users_by_id):
    """Deploys a new entrant's opening cash across several positions,
    exactly like a small personal mini-auction happening in real time via
    the live order book / Bank, using their strategy's own target logic."""
    budget = user.cash * cfg.new_entrant_spend_fraction
    n_buys = int(rng.integers(cfg.new_entrant_buy_count_min, cfg.new_entrant_buy_count_max + 1))
    targets = pick_buy_targets(user.strategy, user, snap, rng, k=n_buys)
    if not targets:
        targets = pick_buy_targets("random", user, snap, rng, k=n_buys)
    if not targets:
        return
    spend_each = budget / len(targets)
    for player_id in targets:
        price = market.current_price(player_id)
        if price <= 0:
            continue
        qty = int(spend_each // price)
        if qty <= 0:
            continue
        available = market.available_liquidity(player_id)
        cap = max(1, int(available * cfg.max_liquidity_take_fraction))
        qty = min(qty, cap)
        market.quick_buy(user, player_id, qty, users_by_id)
