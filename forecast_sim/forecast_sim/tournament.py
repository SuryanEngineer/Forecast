"""
Tournament schedule (event tiers), placement generation, payout curve, and
dividend distribution.

Spec: a chapter/season is 36 Cash Cups + 3 FNCS + 1 Global Championship =
40 events total, each tier with its own prize pool (see
`config.DIVIDEND_POOL_TIERS` / `SimConfig.dividend_pool_tier`). FNCS are
spread roughly evenly through the Cash Cup calendar (after cups 12/24/36)
and the Global Championship is the season finale.
"""

import numpy as np
from .config import SimConfig


def build_event_schedule(cfg: SimConfig) -> list[dict]:
    """Returns an ordered list of {event_idx, tier, prize_pool} dicts,
    tier in {"cash_cup", "fncs", "global"}."""
    pools = cfg.dividend_pools
    schedule = []
    cash_cups_per_fncs = max(1, cfg.cash_cup_count // max(1, cfg.fncs_count))
    cups_placed = 0
    fncs_placed = 0
    for i in range(cfg.cash_cup_count):
        cups_placed += 1
        schedule.append({"tier": "cash_cup", "prize_pool": pools["cash_cup"]})
        due_fncs = min(cfg.fncs_count, cups_placed // cash_cups_per_fncs)
        while fncs_placed < due_fncs:
            schedule.append({"tier": "fncs", "prize_pool": pools["fncs"]})
            fncs_placed += 1
    while fncs_placed < cfg.fncs_count:
        schedule.append({"tier": "fncs", "prize_pool": pools["fncs"]})
        fncs_placed += 1
    for _ in range(cfg.global_count):
        schedule.append({"tier": "global", "prize_pool": pools["global"]})
    for idx, ev in enumerate(schedule, start=1):
        ev["event_idx"] = idx
    return schedule


def run_tournament(players, cfg: SimConfig, rng: np.random.Generator):
    """Generates a full placement order for one tournament.

    performance_score = skill_rating + form + Normal(0, sigma)
    where sigma = volatility_rating * placement_noise_scale, boosted while
    a team-switch rumor is live (rumor uncertainty = more erratic play).

    Returns:
        placements: list of player_id ordered 1st -> last
        noise_by_player: player_id -> the raw noise draw this tournament
            (used downstream to drive sentiment overreaction)
    """
    scores = []
    noise_by_player = {}
    for p in players:
        sigma = p.volatility_rating * cfg.placement_noise_scale
        if p.rumor_active:
            sigma *= cfg.rumor_volatility_multiplier
        noise = rng.normal(0, sigma)
        noise_by_player[p.player_id] = noise
        scores.append((p.player_id, p.skill_rating + p.form + noise))
    scores.sort(key=lambda t: t[1], reverse=True)
    placements = [pid for pid, _ in scores]  # index 0 = 1st place
    return placements, noise_by_player


def payout_curve(n_paid: int, cfg: SimConfig) -> np.ndarray:
    """Weights for placements 1..n_paid, normalized to sum to 1."""
    ranks = np.arange(1, n_paid + 1)
    if cfg.payout_curve == "power":
        weights = np.power(ranks.astype(float), -cfg.payout_power)
    else:  # exponential
        weights = np.power(cfg.payout_exp_decay, ranks - 1)
    return weights / weights.sum()


def compute_payouts(placements: list, prize_pool: float, cfg: SimConfig) -> dict:
    """Returns player_id -> prize money earned this event (0 if outside
    the paid placements). `prize_pool` comes from the event's tier."""
    n_paid = min(cfg.payout_placements, len(placements))
    weights = payout_curve(n_paid, cfg)
    payouts = {pid: 0.0 for pid in placements}
    for i in range(n_paid):
        payouts[placements[i]] = float(weights[i] * prize_pool)
    return payouts


def apply_treasury_yield(users, cfg) -> float:
    """Credits interest on every user's LIQUID cash (cash tied up in open
    orders does not earn it) at `cfg.cash_yield_rate_per_tournament` --
    a genuine money SOURCE, exactly like dividends, just proportional to
    cash held rather than shares held. Returns the total interest paid
    this tournament (0.0 if the rate is 0, i.e. off)."""
    rate = cfg.cash_yield_rate_per_tournament
    if rate <= 0:
        return 0.0
    total = 0.0
    for user in users:
        if user.cash > 0:
            interest = user.cash * rate
            user.cash += interest
            total += interest
    return total


def distribute_dividends(payouts: dict, players_by_id, users_by_id, bank):
    """Turns each player's tournament payout into a per-share dividend and
    pays every shareholder (including the Bank's held shares -- Bank
    dividends are simply not credited anywhere, since Bank cash is not
    tracked and effectively leaves the economy, matching the spec's
    "money paid to the Bank leaves the economy" framing).

    Returns:
        dividend_per_share: player_id -> $/share paid
        total_dividends_paid: total new money injected into user cash
    """
    dividend_per_share = {}
    total_paid = 0.0

    for player_id, payout in payouts.items():
        player = players_by_id[player_id]
        dps = payout / player.shares_issued if player.shares_issued else 0.0
        dividend_per_share[player_id] = dps
        if dps <= 0:
            continue
        for user in users_by_id.values():
            qty = user.shares_of(player_id)
            if qty > 0:
                amount = qty * dps
                user.cash += amount
                total_paid += amount
                user.record(action="dividend", player_id=player_id, qty=qty,
                            per_share=dps, amount=amount)

    return dividend_per_share, total_paid
