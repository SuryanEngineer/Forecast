"""
Bot strategy archetypes.

Two families:
  1. Auction strategies  -- one-shot, used only to allocate starting cash
     across players at the beginning of the season.
  2. Trading strategies   -- used every trading round between tournaments
     to decide whether/what to buy or sell.

Where the spec's one-line description leaves room for interpretation, the
concrete rule chosen is documented in the docstring/comment for that
strategy so it's easy to swap out later.
"""

import numpy as np


# ======================================================================
# Auction strategies (initial cash allocation)
# ======================================================================

def _normalize(weights: np.ndarray) -> np.ndarray:
    total = weights.sum()
    if total <= 0:
        return np.ones_like(weights) / len(weights)
    return weights / total


def auction_weights(strategy: str, players, rng: np.random.Generator) -> np.ndarray:
    """Returns a weight vector (same order as `players`) describing how a
    user following `strategy` splits their auction budget."""
    skills = np.array([p.skill_rating for p in players])
    n = len(players)

    if strategy == "star_chaser":
        # Heavily favors top players: weight = skill^3, so the elite tier
        # dominates the allocation.
        w = np.power(skills, 3)

    elif strategy == "value_investor":
        # Looks for "underpriced" (overlooked) talent: favors mid/high
        # skill players while discounting the very top tier, which the
        # star_chaser crowd will already be bidding up aggressively.
        top_cutoff = np.percentile(skills, 95)
        w = skills.copy()
        w[skills >= top_cutoff] *= 0.15

    elif strategy == "diversified":
        # Spreads broadly across a large random subset of players, roughly
        # evenly.
        subset = rng.random(n) < 0.7
        w = np.where(subset, 1.0, 0.05)

    elif strategy == "momentum":
        # No tournament history exists yet at the initial auction, so
        # "recent performance" doesn't exist. We approximate with a mild
        # preference for already-buzzy (high skill) players plus noise,
        # since that's the closest available signal pre-season.
        w = skills * rng.uniform(0.5, 1.5, size=n)

    else:  # "random"
        w = rng.uniform(0.1, 1.0, size=n)

    return _normalize(w)


# ======================================================================
# Trading strategies (post-tournament rounds)
# ======================================================================

class MarketSnapshot:
    """Lightweight bundle of signals trading strategies read from, computed
    once per round by the simulator (avoids recomputation per bot)."""

    def __init__(self, players, market, price_history, last_placements, avg_placements,
                 recent_dividend_per_share=None):
        self.players = players
        self.market = market
        self.price_history = price_history        # player_id -> list of prices
        self.last_placements = last_placements     # player_id -> last placement (1=best)
        self.avg_placements = avg_placements        # player_id -> historical avg placement
        # player_id -> most recent $/share dividend paid (0 if never paid) --
        # used by the value_investor strategy's "buy high dividend yield" rule.
        self.recent_dividend_per_share = recent_dividend_per_share or {}

    def price(self, player_id):
        return self.market.current_price(player_id)

    def recent_price_change(self, player_id, lookback=3):
        hist = self.price_history.get(player_id, [])
        if len(hist) < 2:
            return 0.0
        ref = hist[-min(lookback, len(hist))]
        cur = hist[-1]
        if ref <= 0:
            return 0.0
        return (cur - ref) / ref

    def dividend_yield(self, player_id):
        """Most recent dividend / current price -- a simple per-tournament
        yield proxy (not annualized)."""
        price = self.price(player_id)
        if price <= 0:
            return 0.0
        return self.recent_dividend_per_share.get(player_id, 0.0) / price


def _pick_top(candidates_scores: dict, rng, k=1, prefer_high=True):
    if not candidates_scores:
        return []
    items = list(candidates_scores.items())
    items.sort(key=lambda kv: kv[1], reverse=prefer_high)
    top = items[: max(k * 3, 5)]  # a little randomness among near-ties
    rng.shuffle(top)
    return [pid for pid, _ in top[:k]]


def pick_buy_targets(strategy: str, user, snap: MarketSnapshot, rng: np.random.Generator, k=1):
    players = snap.players

    if strategy == "dividend_hunter":
        # Favors players with strong recent placements (high tournament
        # earnings -> high dividend), i.e. low (better) recent placement.
        scores = {p.player_id: -snap.last_placements.get(p.player_id, 999)
                  for p in players}
        return _pick_top(scores, rng, k, prefer_high=True)

    if strategy == "speculator":
        # "Buys improving players": players whose most recent placement is
        # better than their historical average placement (an upward trend
        # in results, not yet fully reflected in price).
        scores = {}
        for p in players:
            avg = snap.avg_placements.get(p.player_id)
            last = snap.last_placements.get(p.player_id)
            if avg is None or last is None:
                continue
            scores[p.player_id] = avg - last  # positive = improving
        return _pick_top(scores, rng, k, prefer_high=True)

    if strategy == "momentum_trader":
        # Buys recent winners: biggest recent price gainers.
        scores = {p.player_id: snap.recent_price_change(p.player_id) for p in players}
        return _pick_top(scores, rng, k, prefer_high=True)

    if strategy == "contrarian":
        # Buys players whose price recently fell.
        scores = {p.player_id: snap.recent_price_change(p.player_id) for p in players}
        return _pick_top(scores, rng, k, prefer_high=False)

    if strategy == "index_investor":
        # Diversified: prefers players it doesn't already hold (or holds
        # least of), spreading exposure broadly.
        held = user.holdings
        scores = {p.player_id: -held.get(p.player_id, 0) for p in players}
        return _pick_top(scores, rng, k, prefer_high=True)

    if strategy == "hype_chaser":
        # FOMO: chases whatever the community is currently most hyped on,
        # regardless of whether that hype is justified by true skill --
        # buys the players whose sentiment is most inflated above their
        # underlying skill (and rumored-stronger-team players).
        scores = {p.player_id: (p.sentiment - p.skill_rating)
                  + (3.0 if (p.rumor_active and p.rumor_direction > 0) else 0.0)
                  for p in players}
        return _pick_top(scores, rng, k, prefer_high=True)

    if strategy == "smart_money":
        # Fades the crowd: buys players the community has UNDER-rated
        # relative to true skill (panic-sold dips), betting sentiment
        # mean-reverts back up toward fundamentals.
        scores = {p.player_id: p.skill_rating - p.sentiment for p in players}
        return _pick_top(scores, rng, k, prefer_high=True)

    if strategy == "rumor_trader": # noqa
        # Trades team-switch rumors directly: buys players rumored to be
        # joining a stronger lineup, sized by rumor magnitude.
        scores = {p.player_id: p.rumor_magnitude
                  for p in players if p.rumor_active and p.rumor_direction > 0}
        if scores:
            return _pick_top(scores, rng, k, prefer_high=True)
        return []  # no live "joining stronger team" rumor to trade -- sit out

    if strategy == "news_trader":
        # Spec bot type: "React to roster events." Broader than
        # rumor_trader -- reacts to the whole news-event feed (duo
        # changes, new teammates, meta shifts, confirmed/live rumors),
        # via each player's decaying `recent_news_score` (dynamics.py),
        # not just live team-switch rumors.
        scores = {p.player_id: p.recent_news_score
                  + (p.rumor_magnitude if (p.rumor_active and p.rumor_direction > 0) else 0.0)
                  for p in players}
        scores = {pid: s for pid, s in scores.items() if s > 0}
        if scores:
            return _pick_top(scores, rng, k, prefer_high=True)
        return []  # nothing newsworthy right now -- sit out rather than force a trade

    if strategy == "value_investor":
        # Spec bot type: "Buy high dividend yield." Favors players
        # currently paying the best $/share dividend relative to price,
        # i.e. genuinely cheap relative to the cash they're throwing off
        # -- the classic "fundamentals, not hype" approach.
        scores = {p.player_id: snap.dividend_yield(p.player_id) for p in players}
        scores = {pid: s for pid, s in scores.items() if s > 0}
        if scores:
            return _pick_top(scores, rng, k, prefer_high=True)
        # No dividend history yet (e.g. very early in the season) --
        # fall back to skill (the best available proxy for future
        # dividends) rather than sitting out entirely.
        scores = {p.player_id: p.skill_rating for p in players}
        return _pick_top(scores, rng, k, prefer_high=True)

    if strategy == "team_loyalist":
        # Buys more of what it already holds (conviction, doesn't chase
        # anything new); if it holds nothing yet, picks a stable/low-
        # volatility player to start a long-term position in.
        held = [pid for pid, qty in user.holdings.items() if qty > 0]
        if held:
            rng.shuffle(held)
            return held[:k]
        scores = {p.player_id: -p.volatility_rating for p in players}
        return _pick_top(scores, rng, k, prefer_high=True)

    if strategy == "scalper":
        # In-and-out on whatever is currently moving (highest absolute
        # recent price change), regardless of direction.
        scores = {p.player_id: abs(snap.recent_price_change(p.player_id)) for p in players}
        return _pick_top(scores, rng, k, prefer_high=True)

    if strategy == "panic_seller":
        # Panic sellers are defined by their SELL behavior; on the buy
        # side they behave like undirected momentum-chasers.
        scores = {p.player_id: snap.recent_price_change(p.player_id) for p in players}
        return _pick_top(scores, rng, k, prefer_high=True)

    if strategy == "whale":
        # Large, fundamentals-driven bets concentrated in top-skill talent
        # (moves the market when it trades, by design -- see trading.py's
        # size multiplier for this strategy).
        scores = {p.player_id: p.skill_rating ** 2 for p in players}
        return _pick_top(scores, rng, k, prefer_high=True)

    # random
    ids = [p.player_id for p in players]
    rng.shuffle(ids)
    return ids[:k]


def pick_sell_targets(strategy: str, user, snap: MarketSnapshot, rng: np.random.Generator, k=1):
    """Only ever chooses among players the user actually holds shares of."""
    held_ids = [pid for pid, qty in user.holdings.items() if qty > 0]
    if not held_ids:
        return []

    if strategy == "contrarian":
        # Contrarians buy dips, so when selling they take profit on
        # players whose price has recently risen a lot.
        scores = {pid: snap.recent_price_change(pid) for pid in held_ids}
        return _pick_top(scores, rng, k, prefer_high=True)

    if strategy == "momentum_trader":
        # Cuts losers: sells recent decliners.
        scores = {pid: snap.recent_price_change(pid) for pid in held_ids}
        return _pick_top(scores, rng, k, prefer_high=False)

    if strategy == "dividend_hunter":
        # Sells players whose recent results have gotten worse (falling
        # dividend potential).
        scores = {pid: snap.last_placements.get(pid, 999) for pid in held_ids}
        return _pick_top(scores, rng, k, prefer_high=True)  # high (bad) placement = sell

    if strategy == "index_investor":
        # Trims whatever position has grown largest, to stay diversified.
        scores = {pid: user.holdings.get(pid, 0) for pid in held_ids}
        return _pick_top(scores, rng, k, prefer_high=True)

    if strategy == "panic_seller":
        # The defining trait: dumps hard on ANY recent price weakness at
        # all, wildly disproportionate to how much the price actually
        # moved -- a single bad tournament result triggers an exit.
        scores = {pid: -snap.recent_price_change(pid, lookback=1) for pid in held_ids}
        return _pick_top(scores, rng, k, prefer_high=True)

    if strategy == "hype_chaser":
        # Sells whatever has cooled off (sentiment falling back toward
        # skill) to chase the next hot thing.
        scores = {}
        for pid in held_ids:
            pl = snap.market.players_by_id[pid]
            scores[pid] = -(pl.sentiment - pl.skill_rating)
        return _pick_top(scores, rng, k, prefer_high=True)

    if strategy == "smart_money":
        # Takes profit on positions the community has become overhyped on
        # relative to true skill.
        scores = {pid: (snap.market.players_by_id[pid].sentiment
                        - snap.market.players_by_id[pid].skill_rating)
                  for pid in held_ids}
        return _pick_top(scores, rng, k, prefer_high=True)

    if strategy == "rumor_trader":
        # Exits positions rumored to be joining a weaker team / leaving
        # the scene.
        scores = {pid: 1.0 for pid in held_ids
                  if snap.market.players_by_id[pid].rumor_active
                  and snap.market.players_by_id[pid].rumor_direction < 0}
        if scores:
            return _pick_top(scores, rng, k, prefer_high=True)
        return []

    if strategy == "news_trader":
        # Exits positions with bad recent news (negative recent_news_score
        # or a live "leaving/downgrading" rumor).
        scores = {}
        for pid in held_ids:
            pl = snap.market.players_by_id[pid]
            bad = -pl.recent_news_score
            if pl.rumor_active and pl.rumor_direction < 0:
                bad += pl.rumor_magnitude
            if bad > 0:
                scores[pid] = bad
        if scores:
            return _pick_top(scores, rng, k, prefer_high=True)
        return []

    if strategy == "value_investor":
        # Takes profit / rotates out of whatever is now paying the WORST
        # dividend yield among its holdings (fundamentals have weakened
        # relative to price -- time to look elsewhere).
        scores = {pid: -snap.dividend_yield(pid) for pid in held_ids}
        return _pick_top(scores, rng, k, prefer_high=True)

    if strategy == "team_loyalist":
        # Holds through drama -- essentially never voluntarily sells.
        return []

    if strategy == "scalper":
        # Exits whatever's most volatile right now, taking a quick profit
        # or cutting a quick loss either way.
        scores = {pid: abs(snap.recent_price_change(pid)) for pid in held_ids}
        return _pick_top(scores, rng, k, prefer_high=True)

    if strategy == "whale":
        # Trims the largest single position to manage concentration risk.
        scores = {pid: user.holdings.get(pid, 0) for pid in held_ids}
        return _pick_top(scores, rng, k, prefer_high=True)

    # speculator / random: sell a random held position
    rng.shuffle(held_ids)
    return held_ids[:k]


# ======================================================================
# Per-strategy trading behavior profile (sizing, skip odds, order type)
# ======================================================================

# size_mult: scales the quantity/cash of each trade action relative to the
#   generic default (whale moves size, scalper trades small).
# skip_prob: chance a selected bot does nothing this round even though it
#   was chosen to act (team_loyalist mostly sits on its hands).
# limit_prob_override: if set, replaces cfg.limit_order_probability for
#   this strategy (scalpers want fast fills, loyalists are patient).
STRATEGY_PROFILE = {
    "whale":            {"size_mult": 3.5, "skip_prob": 0.0, "limit_prob_override": 0.3},
    "scalper":          {"size_mult": 0.3, "skip_prob": 0.0, "limit_prob_override": 0.15},
    "team_loyalist":    {"size_mult": 0.6, "skip_prob": 0.7, "limit_prob_override": 0.8},
    "panic_seller":     {"size_mult": 1.4, "skip_prob": 0.0, "limit_prob_override": 0.1},
    "hype_chaser":       {"size_mult": 1.2, "skip_prob": 0.0, "limit_prob_override": 0.15},
    # permanent-bot archetypes (spec "Bot Types")
    "news_trader":      {"size_mult": 1.1, "skip_prob": 0.0, "limit_prob_override": 0.2},
    # value_investor trades on fundamentals (dividend yield), not noise --
    # patient, mostly resting orders, lower turnover than the median bot.
    "value_investor":   {"size_mult": 0.9, "skip_prob": 0.2, "limit_prob_override": 0.7},
    # liquidity_provider doesn't go through the generic buy/sell dispatch
    # at all (see trading.py's dedicated market-making routine) -- this
    # entry exists only so get_strategy_profile() never falls through to
    # the default for it.
    "liquidity_provider": {"size_mult": 1.0, "skip_prob": 0.0, "limit_prob_override": 1.0},
}
DEFAULT_PROFILE = {"size_mult": 1.0, "skip_prob": 0.0, "limit_prob_override": None}


def get_strategy_profile(strategy: str) -> dict:
    return STRATEGY_PROFILE.get(strategy, DEFAULT_PROFILE)
