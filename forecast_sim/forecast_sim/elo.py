"""
ELO investing-skill rating (spec: "ELO -- separate from wealth. Measures
investing skill... Performance measured using: Portfolio appreciation
plus Dividend income. Rank by percentile. Bell curve. Higher ELO requires
better percentile to gain rating.")

(Seasonal points were removed -- the system is just investing and
dividends now; ELO is the only skill-tracking metric.)

Updated once per tournament, using each user's net-worth change since the
snapshot taken at the START of that tournament cycle (i.e. this captures
exactly "portfolio appreciation + dividend income" for the period,
deliberately excluding the initial-auction capitalization, which isn't a
return on investing skill).
"""

import numpy as np
from .config import SimConfig


def required_percentile(elo: float, cfg: SimConfig) -> float:
    """The percentile a user needs to hit just to hold their rating flat.
    Bell-curve difficulty: the higher your current ELO, the better you
    have to perform (relative to everyone else, this period) to gain
    more; a low-ELO user only needs a modest showing to climb back up."""
    start = cfg.elo_start
    span = max(1.0, start)  # avoid div by zero if elo_start were ever 0
    frac = (elo - start) / span
    frac = float(np.clip(frac, -1.0, 1.0))
    lo, hi = 100.0 - cfg.elo_required_percentile_at_2x, cfg.elo_required_percentile_at_2x
    # frac in [-1, 1] -> required percentile in [lo, hi], centered on
    # elo_required_percentile_at_start when frac == 0
    mid = cfg.elo_required_percentile_at_start
    if frac >= 0:
        return mid + frac * (hi - mid)
    return mid + frac * (mid - lo)


def update_elo(users, cfg: SimConfig, net_worth_lookup):
    """Snapshot-to-period-return -> percentile rank -> ELO update, for
    every user (bots included, for a uniform leaderboard -- reporting
    typically filters to humans). `net_worth_lookup(user) -> float`
    should include cash + escrowed order cash + equity."""
    period_returns = {}
    for u in users:
        prev = u.prev_snapshot_net_worth if u.prev_snapshot_net_worth else 1.0
        now = net_worth_lookup(u)
        period_returns[u.user_id] = (now - prev) / prev if prev > 0 else 0.0

    n = len(users)
    if n <= 1:
        for u in users:
            u.prev_snapshot_net_worth = net_worth_lookup(u)
        return

    ordered = sorted(users, key=lambda u: period_returns[u.user_id])
    percentile_by_uid = {}
    for rank, u in enumerate(ordered):
        percentile_by_uid[u.user_id] = 100.0 * rank / (n - 1)

    for u in users:
        pctile = percentile_by_uid[u.user_id]
        req = required_percentile(u.elo, cfg)
        delta = cfg.elo_k * (pctile - req) / 50.0
        u.elo = float(max(100.0, u.elo + delta))
        u.elo_history.append(u.elo)
        u.prev_snapshot_net_worth = net_worth_lookup(u)
