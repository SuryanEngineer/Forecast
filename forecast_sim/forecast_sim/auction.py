"""
Initial auction: every user allocates starting cash across players
simultaneously; shares are allocated proportionally to each player's total
bids, and the implied initial price is total_bids / shares_issued.
Players who receive zero bids leave all shares with the Bank at the
baseline price (there's no way to define a proportional split of zero).

Every participant (human or bot) also pays a flat, one-time auction entry
fee (`cfg.auction_entry_fee_flat`) before their bidding budget is computed
-- money removed permanently from the economy, tracked in
`market.auction_fees_removed`.
"""

import numpy as np
from .config import SimConfig
from .strategies import auction_weights


def run_initial_auction(players, users, market, cfg: SimConfig, rng: np.random.Generator):
    """Mutates `users` (cash, holdings) and `market` (bank inventory,
    last_trade_price) in place. Returns a dict of per-player auction
    summary rows for reporting."""

    # ---- flat entry fee, once per participant, before bidding ----
    total_auction_fees = 0.0
    if cfg.auction_entry_fee_flat > 0:
        for user in users:
            fee = min(cfg.auction_entry_fee_flat, user.cash)
            user.cash -= fee
            total_auction_fees += fee

    total_bids = {p.player_id: 0.0 for p in players}
    bid_matrix = {}  # user_id -> {player_id: bid_amount}

    for user in users:
        spend_fraction = min(cfg.auction_spend_fraction, cfg.auction_spend_cap_fraction)
        budget = user.cash * spend_fraction
        weights = auction_weights(user.auction_strategy, players, rng)
        bids = {p.player_id: float(budget * w) for p, w in zip(players, weights)}
        bid_matrix[user.user_id] = bids
        for pid, amt in bids.items():
            total_bids[pid] += amt

    summary_rows = []
    for p in players:
        tb = total_bids[p.player_id]
        if tb <= 0:
            price = cfg.baseline_price
            market.bank.set_initial_inventory(p.player_id, p.shares_issued)
            allocated = 0
        else:
            # Minimum share price enforced (spec): a player who DOES
            # receive bids still can't clear below this floor. Raising the
            # clearing price above what bids imply is a simplification --
            # per-user cost is still capped at that user's cash below, so
            # nobody can be forced to overspend their bid.
            price = max(tb / p.shares_issued, cfg.min_share_price)

            # Exact apportionment (largest-remainder / Hamilton method):
            # each bidder's exact fractional entitlement is floored, then
            # the few leftover shares (shares_issued - sum(floors), always
            # a small non-negative number) go one at a time to whoever had
            # the largest fractional remainder. This guarantees shares
            # allocated across all bidders + Bank sum to EXACTLY
            # shares_issued -- independently rounding each bidder's share
            # (the previous approach) can over- or under-allocate the
            # total by dozens of shares per player once there are hundreds
            # of bidders, which silently inflates/deflates the real share
            # supply (and therefore every future dividend payout) with no
            # visible symptom until you specifically check share
            # conservation, which is exactly how this was found.
            bidders = [u for u in users if bid_matrix[u.user_id][p.player_id] > 0]
            exact = {u.user_id: (bid_matrix[u.user_id][p.player_id] / tb) * p.shares_issued
                     for u in bidders}
            floor_shares = {uid: int(v) for uid, v in exact.items()}
            remainder = p.shares_issued - sum(floor_shares.values())
            # hand out the leftover shares to the largest fractional
            # remainders first (ties broken by user_id for determinism)
            order = sorted(exact.keys(), key=lambda uid: (exact[uid] - floor_shares[uid]), reverse=True)
            final_shares = dict(floor_shares)
            for uid in order[:max(0, remainder)]:
                final_shares[uid] += 1

            allocated = 0
            for user in bidders:
                shares = final_shares[user.user_id]
                if shares <= 0:
                    continue
                cost = min(shares * price, user.cash)  # guard against rounding/price-floor overspend
                user.cash -= cost
                user.holdings[p.player_id] = user.holdings.get(p.player_id, 0) + shares
                allocated += shares
            leftover = p.shares_issued - allocated
            if leftover > 0:
                market.bank.set_initial_inventory(p.player_id, leftover)

        p.last_trade_price = price
        summary_rows.append({
            "player_id": p.player_id,
            "name": p.name,
            "skill_rating": p.skill_rating,
            "total_bids": tb,
            "initial_price": price,
            "shares_to_bank": market.bank.inventory.get(p.player_id, 0),
        })

    market.auction_fees_removed += total_auction_fees
    return summary_rows
