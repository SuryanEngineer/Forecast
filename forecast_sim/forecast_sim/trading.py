"""
Executes one round of bot trading activity between tournaments.
"""

import numpy as np
from .config import SimConfig
from .strategies import MarketSnapshot, pick_buy_targets, pick_sell_targets, get_strategy_profile


def run_trading_round(users, players_by_id, market, snap: MarketSnapshot,
                       cfg: SimConfig, rng: np.random.Generator, users_by_id):
    n_active = max(1, int(len(users) * cfg.participation_rate))
    active_users = list(rng.choice(users, size=n_active, replace=False))
    rng.shuffle(active_users)

    for user in active_users:
        if user.strategy == "liquidity_provider":
            _run_market_maker(user, market, snap, cfg, rng, users_by_id)
            continue

        profile = get_strategy_profile(user.strategy)
        if profile["skip_prob"] > 0 and rng.random() < profile["skip_prob"]:
            continue

        # Decide buy vs. sell: sell only possible if holding something;
        # otherwise default to buy. ~45% chance to consider selling if
        # they hold positions (keeps portfolios from only ever growing).
        can_sell = any(q > 0 for q in user.holdings.values())
        do_sell = can_sell and rng.random() < 0.45

        if do_sell:
            targets = pick_sell_targets(user.strategy, user, snap, rng, k=1)
            if not targets:
                continue
            player_id = targets[0]
            have = user.shares_of(player_id)
            qty = max(1, int(have * cfg.max_trade_share_fraction * profile["size_mult"] * rng.uniform(0.4, 1.0)))
            qty = min(qty, have)
            if qty <= 0:
                continue
            _execute_sell(user, player_id, qty, market, cfg, rng, users_by_id, profile)
        else:
            targets = pick_buy_targets(user.strategy, user, snap, rng, k=1)
            if not targets:
                continue
            player_id = targets[0]
            price = snap.price(player_id)
            if price <= 0:
                continue
            spend = user.cash * cfg.max_trade_cash_fraction * profile["size_mult"] * rng.uniform(0.3, 1.0)
            spend = min(spend, user.cash)
            qty = int(spend // price)
            if qty <= 0:
                continue
            _execute_buy(user, player_id, qty, price, market, cfg, rng, users_by_id, profile)


def _execute_buy(user, player_id, qty, ref_price, market, cfg, rng, users_by_id, profile):
    limit_prob = profile["limit_prob_override"] if profile["limit_prob_override"] is not None \
        else cfg.limit_order_probability
    if rng.random() < limit_prob:
        limit_price = ref_price * (1 - cfg.limit_order_offset)
        max_affordable = int(user.cash // (limit_price * (1 + market.transaction_fee_rate))) if limit_price > 0 else 0
        qty = min(qty, max_affordable)
        if qty <= 0:
            return
        market.submit_limit_buy(user, player_id, qty, limit_price, users_by_id)
    else:
        available = market.available_liquidity(player_id)
        cap = max(1, int(available * cfg.max_liquidity_take_fraction))
        qty = min(qty, cap)
        if qty <= 0:
            return
        market.quick_buy(user, player_id, qty, users_by_id)


def _execute_sell(user, player_id, qty, market, cfg, rng, users_by_id, profile):
    limit_prob = profile["limit_prob_override"] if profile["limit_prob_override"] is not None \
        else cfg.limit_order_probability
    if rng.random() < limit_prob:
        ref_price = market.current_price(player_id)
        limit_price = ref_price * (1 + cfg.limit_order_offset)
        market.submit_limit_sell(user, player_id, qty, limit_price, users_by_id)
    else:
        market.quick_sell(user, player_id, qty, users_by_id)


# ======================================================================
# Liquidity-provider market making (spec bot type: "Constantly maintain
# bids and asks.")
# ======================================================================

def _run_market_maker(user, market, snap: MarketSnapshot, cfg: SimConfig,
                       rng: np.random.Generator, users_by_id):
    """A liquidity_provider quotes BOTH sides of the book for its assigned
    players every round it's chosen to act: a small resting buy below the
    current price, and (if it's holding any inventory in that player) a
    small resting sell above it. Unlike the directional strategies, it
    doesn't chase signals -- disagreement about direction isn't the point,
    continuous two-sided depth is."""
    if not user.mm_players:
        return
    targets = list(user.mm_players)
    rng.shuffle(targets)
    targets = targets[:2]  # quote up to 2 of its assigned players per round

    for player_id in targets:
        price = snap.price(player_id)
        if price <= 0:
            continue

        # ---- bid side ----
        bid_price = price * (1 - cfg.mm_spread_offset)
        bid_budget = user.cash * cfg.mm_quote_size_fraction
        unit_cost = bid_price * (1 + market.transaction_fee_rate)
        qty = int(bid_budget // unit_cost) if unit_cost > 0 else 0
        if qty > 0:
            market.submit_limit_buy(user, player_id, qty, bid_price, users_by_id)

        # ---- ask side (only if it actually holds inventory to quote) ----
        have = user.shares_of(player_id)
        if have > 0:
            ask_price = price * (1 + cfg.mm_spread_offset)
            ask_qty = max(1, int(have * cfg.mm_quote_size_fraction * 4))
            ask_qty = min(ask_qty, have)
            if ask_qty > 0:
                market.submit_limit_sell(user, player_id, ask_qty, ask_price, users_by_id)
