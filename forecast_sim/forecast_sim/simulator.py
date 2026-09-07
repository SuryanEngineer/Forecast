"""
Top-level Simulator: wires together population generation, the initial
auction, and the repeated tournament -> dividends -> trading loop.

v2: tiered tournament schedule (Cash Cup / FNCS / Global), permanent bot
population + paced human growth, transaction fees, simulated news
(rumors/retirement/duo changes/slumps/meta shifts), and ELO / seasonal
points.
"""

import numpy as np
from .config import SimConfig
from .population import generate_players, generate_users
from .market import Market
from .auction import run_initial_auction
from .tournament import (build_event_schedule, run_tournament, compute_payouts,
                          distribute_dividends, apply_treasury_yield)
from .trading import run_trading_round
from .strategies import MarketSnapshot
from .metrics import MetricsTracker
from .dynamics import pre_tournament_update, update_sentiment, generate_news_events
from .elo import update_elo
from . import entrants as entrants_mod


class Simulator:
    def __init__(self, cfg: SimConfig = None):
        self.cfg = cfg or SimConfig()
        self.rng = np.random.default_rng(self.cfg.random_seed)

        self.players = generate_players(self.cfg, self.rng)
        self.users = generate_users(self.cfg, self.rng)
        self.users_by_id = {u.user_id: u for u in self.users}
        self.players_by_id = {p.player_id: p for p in self.players}
        self.used_player_names = {p.name for p in self.players}

        self.market = Market(self.players, self.cfg.bank_spread, self.cfg.baseline_price,
                              transaction_fee_rate=self.cfg.transaction_fee_rate)

        self.metrics = MetricsTracker(self.players, self.users, self.market)

        # placement history for dividend_hunter / speculator strategy signals
        self.last_placements = {}   # player_id -> 1-based rank in most recent tournament
        self.avg_placements = {}    # player_id -> running average placement
        self._placement_counts = {p.player_id: 0 for p in self.players}
        self.recent_dividend_per_share = {}  # player_id -> most recent $/share dividend

        self.auction_summary = None
        self.event_schedule = build_event_schedule(self.cfg)
        self.tournament_results = []  # list of dicts: tournament idx -> placements/payouts

        # new-entrant / rumor / news bookkeeping for reporting
        entrants_mod.init_id_counter(self.cfg.num_initial_humans + self.cfg.num_bots + 1)
        self._num_human_entrants_so_far = 0
        self._entrant_join_prob, self._entrant_batch_scale = entrants_mod.join_pacing(self.cfg)
        self.entrant_log = []          # one row per user who joined post-auction
        self.rumor_started_count = 0
        self.rumor_confirmed_count = 0
        self.rumor_debunked_count = 0
        self.news_log = []             # every fired news event, all types
        self.retirement_count = 0
        self.cumulative_treasury_yield_paid = 0.0

    # ------------------------------------------------------------------
    def setup(self):
        self.auction_summary = run_initial_auction(
            self.players, self.users, self.market, self.cfg, self.rng
        )
        self.metrics.update_price_history()
        # Baseline for "inflation" comparisons: total cash *after* the
        # initial auction (auction spend capitalizes the players, it's not
        # trading-driven inflation/deflation).
        self.post_auction_total_cash = sum(u.cash for u in self.users)
        for u in self.users:
            u.prev_snapshot_net_worth = u.net_worth(lambda pid: self.market.current_price(pid))

    def _update_placements(self, placements):
        for rank, pid in enumerate(placements, start=1):
            self.last_placements[pid] = rank
            n = self._placement_counts.get(pid, 0)
            prev_avg = self.avg_placements.get(pid, rank)
            new_avg = (prev_avg * n + rank) / (n + 1)
            self.avg_placements[pid] = new_avg
            self._placement_counts[pid] = n + 1

    def _count_rumor_transitions(self, before_active: dict):
        for p in self.players:
            was_active = before_active.get(p.player_id, False)
            if not was_active and p.rumor_active:
                self.rumor_started_count += 1
            if was_active and not p.rumor_active:
                if p.last_rumor_confirmed:
                    self.rumor_confirmed_count += 1
                else:
                    self.rumor_debunked_count += 1



    def run(self, progress_every: int = 20):
        for t, event in enumerate(self.event_schedule, start=1):
            before_active = {p.player_id: p.rumor_active for p in self.players}
            pre_tournament_update(self.players, self.cfg, self.rng)

            news_this_round = generate_news_events(
                self.players, self.players_by_id, self.cfg, self.rng, t, self.used_player_names
            )
            self.news_log.extend(news_this_round)
            self.retirement_count += sum(1 for e in news_this_round if e["event_type"] == "retirement")
            self._count_rumor_transitions(before_active)

            placements, noise_by_player = run_tournament(self.players, self.cfg, self.rng)
            payouts = compute_payouts(placements, event["prize_pool"], self.cfg)
            self._update_placements(placements)

            dividend_per_share, total_dividends = distribute_dividends(
                payouts, self.players_by_id, self.users_by_id, self.market.bank
            )
            self.recent_dividend_per_share.update(dividend_per_share)

            treasury_yield_this_round = apply_treasury_yield(self.users, self.cfg)
            self.cumulative_treasury_yield_paid += treasury_yield_this_round

            update_sentiment(self.players, noise_by_player, self.cfg, self.rng)

            self.tournament_results.append({
                "tournament": t,
                "tier": event["tier"],
                "prize_pool": event["prize_pool"],
                "placements": placements,
                "payouts": payouts,
                "dividend_per_share": dividend_per_share,
                "total_dividends_paid": total_dividends,
            })

            # trading rounds (+ chance of new human entrants joining each round)
            for _r in range(self.cfg.trading_rounds_per_tournament):
                self.market.advance_round()
                self.market.expire_stale_orders(self.cfg.order_max_age_rounds, self.users_by_id)
                prices = self.metrics.update_price_history()
                snap = MarketSnapshot(
                    self.players, self.market, self.metrics.price_history,
                    self.last_placements, self.avg_placements,
                    recent_dividend_per_share=self.recent_dividend_per_share,
                )

                new_users, self._num_human_entrants_so_far = entrants_mod.maybe_spawn_new_users(
                    self.users, self.users_by_id, self.cfg, self.rng, t,
                    self._num_human_entrants_so_far, self._entrant_join_prob,
                    batch_scale=self._entrant_batch_scale,
                )
                for u in new_users:
                    entrants_mod.onboard_new_user(u, self.market, snap, self.cfg, self.rng, self.users_by_id)
                    self.entrant_log.append({
                        "user_id": u.user_id, "joined_tournament": t,
                        "strategy": u.strategy, "starting_cash": u.starting_cash_at_join,
                    })

                run_trading_round(
                    self.users, self.players_by_id, self.market, snap,
                    self.cfg, self.rng, self.users_by_id,
                )

            escrow_by_user = self.market.escrowed_cash_by_user()
            price_fn = self.market.current_price

            def _net_worth_of(user, _escrow=escrow_by_user, _price=price_fn):
                return user.net_worth(_price) + _escrow.get(user.user_id, 0.0)

            update_elo(self.users, self.cfg, _net_worth_of)

            self.metrics.snapshot(t, total_dividends, self.users_by_id,
                                   treasury_yield_paid_this_round=treasury_yield_this_round)

            if progress_every and t % progress_every == 0:
                n_humans = sum(1 for u in self.users if not u.is_bot)
                print(f"  ...event {t}/{len(self.event_schedule)} ({event['tier']}) complete "
                      f"({n_humans} humans, {self.cfg.num_bots} bots)")

        return self.metrics.as_dataframes()
