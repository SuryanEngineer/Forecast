"""
Metrics collection. Snapshots are taken after every tournament (post
dividend distribution, post trading rounds) and accumulated into
DataFrames the caller can dump to CSV / chart at the end of the run.

Extended for the v2 spec's "Metrics" / "Success Metrics" sections: Gini
coefficient, cash ratio, top 10%/1% wealth share, trading volume as a %
of market cap, and the money-sink fee totals (auction fee, transaction
fee), alongside the original economy/market/ownership/user/player series.
Per-user turnover, passive-holder %, and the dividend-vs-appreciation
return split are run-level (not per-tournament) computations done at the
end in main.py / success_criteria.py, since they're naturally "over the
whole run" figures rather than a time series.
"""

import numpy as np
import pandas as pd


def gini(values) -> float:
    """Standard Gini coefficient (0 = perfectly equal, 1 = maximally
    unequal). Values must be non-negative; shifts negatives up to 0 first
    since net worth can technically be handled here even if it never goes
    below the cash floor in practice."""
    arr = np.array(values, dtype=float)
    if arr.size == 0:
        return 0.0
    arr = arr - arr.min() if arr.min() < 0 else arr
    if arr.sum() <= 0:
        return 0.0
    arr = np.sort(arr)
    n = arr.size
    cum = np.cumsum(arr)
    return float((n + 1 - 2 * (cum.sum() / cum[-1])) / n)


def top_share(values, frac: float) -> float:
    """Fraction of total `values` held by the top `frac` (e.g. 0.10 for
    top 10%) of entries, by value."""
    arr = np.sort(np.array(values, dtype=float))[::-1]
    total = arr.sum()
    if total <= 0:
        return 0.0
    k = max(1, int(round(len(arr) * frac)))
    return float(arr[:k].sum() / total)


class MetricsTracker:
    def __init__(self, players, users, market):
        self.players = players
        self.users = users
        self.market = market

        self.economy_rows = []
        self.market_rows = []
        self.ownership_rows = []
        self.user_rows = []
        self.player_rows = []
        self.elo_rows = []

        # long-form time series for charting
        self.price_history_rows = []     # tournament, player_id, price
        self.marketcap_history_rows = []  # tournament, total_market_cap

        # running price history per player_id -> list of prices (for
        # momentum/contrarian strategy signals)
        self.price_history = {p.player_id: [p.last_trade_price] for p in players}

    def _current_prices(self):
        return {p.player_id: self.market.current_price(p.player_id) for p in self.players}

    def update_price_history(self):
        prices = self._current_prices()
        for pid, price in prices.items():
            self.price_history.setdefault(pid, []).append(price)
        return prices

    def snapshot(self, tournament_idx, dividends_paid_this_round, users_by_id,
                 treasury_yield_paid_this_round=0.0):
        self._cumulative_treasury_yield = getattr(self, "_cumulative_treasury_yield", 0.0) \
            + treasury_yield_paid_this_round
        prices = self._current_prices()
        shares_issued = {p.player_id: p.shares_issued for p in self.players}
        bank_inv = self.market.bank.inventory

        # ---- market cap per player (circulating, i.e. total shares incl. bank) ----
        market_caps = {pid: prices[pid] * shares_issued[pid] for pid in prices}
        total_market_cap = sum(market_caps.values())

        # ---- economy ----
        total_user_cash = sum(u.cash for u in self.users)
        total_equity_value = sum(
            u.shares_of(pid) * prices[pid] for u in self.users for pid in u.holdings if u.holdings[pid] > 0
        )
        escrowed_buy_cash = self.market.total_escrowed_buy_cash()
        # "Money supply" = liquid cash + cash reserved in open buy orders.
        # Both are still the user's money, just one is temporarily locked
        # up as escrow for an unfilled limit order. Equity (share value)
        # is deliberately excluded -- it's wealth, not money supply.
        total_money = total_user_cash + escrowed_buy_cash
        total_shares_outstanding = sum(shares_issued.values())
        bank_shares_total = sum(bank_inv.values())
        bank_share_pct = bank_shares_total / total_shares_outstanding if total_shares_outstanding else 0.0
        # Spec "Cash ratio: 15-30%" healthy range -- cash's share of total
        # investor net worth (cash + escrow + equity).
        total_investor_net_worth = total_money + total_equity_value
        cash_ratio = total_money / total_investor_net_worth if total_investor_net_worth else 0.0
        self.economy_rows.append({
            "tournament": tournament_idx,
            "num_users": len(self.users),
            "num_humans": sum(1 for u in self.users if not u.is_bot),
            "num_bots": sum(1 for u in self.users if u.is_bot),
            "total_user_cash": total_user_cash,
            "total_escrowed_buy_cash": escrowed_buy_cash,
            "total_equity_value": total_equity_value,
            "total_money_supply": total_money,
            "total_market_cap": total_market_cap,
            "cash_ratio": cash_ratio,
            "dividends_paid_this_round": dividends_paid_this_round,
            "treasury_yield_paid_this_round": treasury_yield_paid_this_round,
            "cumulative_treasury_yield_paid": self._cumulative_treasury_yield,
            "cumulative_bank_cash_absorbed": self.market.bank.cash_absorbed,
            "cumulative_bank_cash_injected": self.market.bank.cash_injected,
            "cumulative_transaction_fees_removed": self.market.transaction_fees_removed,
            "cumulative_auction_fees_removed": self.market.auction_fees_removed,
            "bank_shares_held": bank_shares_total,
            "bank_share_pct_of_supply": bank_share_pct,
        })
        self.marketcap_history_rows.append({"tournament": tournament_idx, "total_market_cap": total_market_cap})

        # ---- market (volume + liquidity) ----
        recent_trades = [t for t in self.market.trade_log if t.timestamp > getattr(self, "_last_clock", 0)]
        volume_shares = sum(t.quantity for t in recent_trades)
        volume_notional = sum(t.quantity * t.price for t in recent_trades)
        self._last_clock = self.market._clock

        spreads = []
        depths = []
        for p in self.players:
            s = self.market.bid_ask_spread(p.player_id)
            if s is not None:
                spreads.append(s)
            b, a = self.market.books[p.player_id].depth()
            depths.append(b + a)
        avg_spread = float(np.mean(spreads)) if spreads else None
        avg_depth = float(np.mean(depths)) if depths else 0.0
        volume_pct_of_market_cap = volume_notional / total_market_cap if total_market_cap else 0.0

        self.market_rows.append({
            "tournament": tournament_idx,
            "trading_volume_shares": volume_shares,
            "trading_volume_notional": volume_notional,
            "trading_volume_pct_of_market_cap": volume_pct_of_market_cap,
            "avg_bid_ask_spread": avg_spread,
            "avg_order_book_depth": avg_depth,
            "players_with_active_market": len(spreads),
        })

        # ---- ownership ----
        largest_pct = {}
        hhi = {}
        active_holders = {}
        for p in self.players:
            pid = p.player_id
            total_shares = shares_issued[pid]
            holder_shares = [u.shares_of(pid) for u in self.users if u.shares_of(pid) > 0]
            bank_shares = bank_inv.get(pid, 0)
            n_holders = len(holder_shares) + (1 if bank_shares > 0 else 0)
            active_holders[pid] = n_holders
            if total_shares <= 0:
                largest_pct[pid] = 0.0
                hhi[pid] = 0.0
                continue
            fractions = [s / total_shares for s in holder_shares]
            if bank_shares > 0:
                fractions.append(bank_shares / total_shares)
            largest_pct[pid] = max(fractions) if fractions else 0.0
            hhi[pid] = sum(f ** 2 for f in fractions)

        self.ownership_rows.append({
            "tournament": tournament_idx,
            "avg_largest_owner_pct": float(np.mean(list(largest_pct.values()))),
            "max_largest_owner_pct": float(np.max(list(largest_pct.values()))),
            "avg_ownership_hhi": float(np.mean(list(hhi.values()))),
            "avg_active_holders_per_player": float(np.mean(list(active_holders.values()))),
        })

        # ---- users ----
        escrow_by_user = self.market.escrowed_cash_by_user()
        net_worths = {
            u.user_id: u.net_worth(lambda pid: prices.get(pid, 0.0)) + escrow_by_user.get(u.user_id, 0.0)
            for u in self.users
        }
        human_net_worths = {u.user_id: net_worths[u.user_id] for u in self.users if not u.is_bot}
        sorted_nw = sorted(net_worths.items(), key=lambda kv: kv[1], reverse=True)
        top_users = sorted_nw[:5]
        bottom_users = sorted_nw[-5:]
        nw_values = np.array(list(net_worths.values()))
        human_nw_values = np.array(list(human_net_worths.values())) if human_net_worths else nw_values
        self.user_rows.append({
            "tournament": tournament_idx,
            "mean_net_worth": float(np.mean(nw_values)),
            "median_net_worth": float(np.median(nw_values)),
            "std_net_worth": float(np.std(nw_values)),
            "min_net_worth": float(np.min(nw_values)),
            "max_net_worth": float(np.max(nw_values)),
            "top_user_id": top_users[0][0],
            "top_user_net_worth": top_users[0][1],
            "bottom_user_id": bottom_users[0][0],
            "bottom_user_net_worth": bottom_users[0][1],
            "gini_net_worth_all": gini(nw_values),
            "gini_net_worth_humans": gini(human_nw_values),
            "top10pct_wealth_share_all": top_share(nw_values, 0.10),
            "top1pct_wealth_share_all": top_share(nw_values, 0.01),
        })

        # ---- ELO (humans vs bots) ----
        human_elo = [u.elo for u in self.users if not u.is_bot]
        bot_elo = [u.elo for u in self.users if u.is_bot]
        self.elo_rows.append({
            "tournament": tournament_idx,
            "avg_human_elo": float(np.mean(human_elo)) if human_elo else None,
            "median_human_elo": float(np.median(human_elo)) if human_elo else None,
            "max_human_elo": float(np.max(human_elo)) if human_elo else None,
            "min_human_elo": float(np.min(human_elo)) if human_elo else None,
            "avg_bot_elo": float(np.mean(bot_elo)) if bot_elo else None,
        })

        # ---- players ----
        sorted_players = sorted(market_caps.items(), key=lambda kv: kv[1], reverse=True)
        highest = sorted_players[0]
        lowest = sorted_players[-1]
        gains = {}
        for pid in prices:
            hist = self.price_history.get(pid, [])
            if len(hist) >= 2 and hist[-2] > 0:
                gains[pid] = (hist[-1] - hist[-2]) / hist[-2]
            else:
                gains[pid] = 0.0
        sorted_gains = sorted(gains.items(), key=lambda kv: kv[1], reverse=True)
        biggest_gainer = sorted_gains[0]
        biggest_loser = sorted_gains[-1]

        self.player_rows.append({
            "tournament": tournament_idx,
            "highest_valued_player_id": highest[0],
            "highest_market_cap": highest[1],
            "lowest_valued_player_id": lowest[0],
            "lowest_market_cap": lowest[1],
            "biggest_gainer_player_id": biggest_gainer[0],
            "biggest_gainer_pct": biggest_gainer[1],
            "biggest_loser_player_id": biggest_loser[0],
            "biggest_loser_pct": biggest_loser[1],
        })

        for pid, price in prices.items():
            self.price_history_rows.append({"tournament": tournament_idx, "player_id": pid, "price": price})

    # ------------------------------------------------------------------
    def as_dataframes(self):
        return {
            "economy": pd.DataFrame(self.economy_rows),
            "market": pd.DataFrame(self.market_rows),
            "ownership": pd.DataFrame(self.ownership_rows),
            "users": pd.DataFrame(self.user_rows),
            "players": pd.DataFrame(self.player_rows),
            "price_history": pd.DataFrame(self.price_history_rows),
            "elo": pd.DataFrame(self.elo_rows),
        }
