"""
Builds the plain-English summary_report.txt: the original "Goals of
Simulation" narrative answers, plus v2 additions (tiered tournaments,
money-sink fees, cash treasury yield, ELO leaderboard, simulated news, and the
spec's "Success Metrics" pass/fail evaluation via success_criteria.py).
"""

import os
import numpy as np
import pandas as pd

from . import success_criteria


def build_summary_report(sim, dfs, user_perf_df, out_dir, build_health_check_lines):
    cfg = sim.cfg
    econ = dfs["economy"]
    own = dfs["ownership"]
    mkt = dfs["market"]
    elo_df = dfs["elo"]

    start_cash_total_raw = (cfg.num_initial_humans + cfg.num_bots) * cfg.starting_cash
    start_cash_total = sim.post_auction_total_cash
    end_cash_total = econ["total_money_supply"].iloc[-1]
    end_market_cap = econ["total_market_cap"].iloc[-1]
    total_dividends = econ["dividends_paid_this_round"].sum()
    total_treasury_yield = econ["treasury_yield_paid_this_round"].sum() if "treasury_yield_paid_this_round" in econ else 0.0
    cash_inflation_pct = (end_cash_total - start_cash_total) / start_cash_total * 100

    zero_cash_users = sum(1 for u in sim.users if u.cash <= 0)

    humans_df = user_perf_df[~user_perf_df["is_bot"]] if user_perf_df is not None else None
    strategy_final_networth = {}
    for u in sim.users:
        strategy_final_networth.setdefault(u.strategy, []).append(
            u.net_worth(lambda pid: sim.market.current_price(pid))
        )
    strategy_avg = {s: sum(v) / len(v) for s, v in strategy_final_networth.items()}
    best_strategy = max(strategy_avg, key=strategy_avg.get)
    worst_strategy = min(strategy_avg, key=strategy_avg.get)

    max_owner_final = own["max_largest_owner_pct"].iloc[-1] * 100
    avg_owner_final = own["avg_largest_owner_pct"].iloc[-1] * 100
    hhi_final = own["avg_ownership_hhi"].iloc[-1]

    prices_df = dfs["price_history"]
    final_t = prices_df["tournament"].max()
    first_t = prices_df["tournament"].min()
    p0 = prices_df[prices_df["tournament"] == first_t].set_index("player_id")["price"]
    p1 = prices_df[prices_df["tournament"] == final_t].set_index("player_id")["price"]
    player_ids = sorted(set(p0.index) & set(p1.index))
    total_start_val = sum(p0[pid] * sim.players_by_id[pid].shares_issued for pid in player_ids
                          if pid in sim.players_by_id)
    total_end_val = sum(p1[pid] * sim.players_by_id[pid].shares_issued for pid in player_ids
                        if pid in sim.players_by_id)

    sorted_players = sorted(sim.players, key=lambda p: p.skill_rating, reverse=True)
    top_decile = sorted_players[: max(1, len(sorted_players) // 10)]
    top_decile_ids = {p.player_id for p in top_decile}
    top_decile_cap = sum(p1.get(pid, 0) * sim.players_by_id[pid].shares_issued for pid in top_decile_ids
                         if pid in sim.players_by_id)
    top_decile_share = top_decile_cap / total_end_val * 100 if total_end_val else 0.0

    liquidity_trend = "improved" if mkt["avg_bid_ask_spread"].iloc[-1] < mkt["avg_bid_ask_spread"].dropna().iloc[0] \
        else "worsened"

    lines = []
    lines.append("FORECAST ECONOMY SIMULATOR - RUN SUMMARY")
    lines.append("=" * 55)
    n_humans_final = sum(1 for u in sim.users if not u.is_bot)
    lines.append(f"Players: {cfg.num_players}  Humans: {cfg.num_initial_humans} -> {n_humans_final}  "
                 f"Bots: {cfg.num_bots}  Events: {cfg.num_tournaments} "
                 f"({cfg.cash_cup_count} Cash Cups / {cfg.fncs_count} FNCS / {cfg.global_count} Global)")
    lines.append(f"Dividend tier: {cfg.dividend_pool_tier} {cfg.dividend_pools}  "
                 f"Transaction fee: {cfg.transaction_fee_rate*100:.2f}%  Bank spread: {cfg.bank_spread*100:.0f}%  "
                 f"Auction fee: ${cfg.auction_entry_fee_flat:,.0f} flat  "
                 f"Cash yield: {cfg.cash_yield_rate_per_tournament*100:.3f}%/event  "
                 f"New human entrants: {'on' if cfg.enable_new_entrants else 'off'}")
    lines.append(f"Random seed: {cfg.random_seed}")
    lines.append("")
    lines.append("1) Does inflation become excessive?")
    lines.append(f"   Total money supply went from ${start_cash_total:,.0f} (post-auction) to "
                 f"${end_cash_total:,.0f} ({cash_inflation_pct:+.1f}%). Money SOURCES: dividends "
                 f"${total_dividends:,.0f}, cash treasury yield ${total_treasury_yield:,.0f}. Money SINKS "
                 f"(fees removed permanently): "
                 f"${econ['cumulative_transaction_fees_removed'].iloc[-1] + econ['cumulative_auction_fees_removed'].iloc[-1]:,.0f} "
                 f"(transaction: ${econ['cumulative_transaction_fees_removed'].iloc[-1]:,.0f}, "
                 f"auction: ${econ['cumulative_auction_fees_removed'].iloc[-1]:,.0f}). "
                 f"(Pre-auction starting cash was ${start_cash_total_raw:,.0f}.)")
    lines.append("")
    lines.append("2) Do players (users) run out of cash?")
    lines.append(f"   {zero_cash_users} of {len(sim.users)} users (humans + bots) ended with $0 or negative cash.")
    lines.append("")
    lines.append("3) Does one strategy dominate?")
    lines.append(f"   Best-performing strategy (avg final net worth): {best_strategy} "
                 f"(${strategy_avg[best_strategy]:,.0f}). Weakest: {worst_strategy} "
                 f"(${strategy_avg[worst_strategy]:,.0f}).")
    for s, v in sorted(strategy_avg.items(), key=lambda kv: kv[1], reverse=True):
        lines.append(f"     - {s}: ${v:,.0f} avg net worth")
    lines.append("")
    lines.append("4) Do top players absorb the entire economy?")
    lines.append(f"   Top 10%-by-skill players hold {top_decile_share:.1f}% of total market cap at the end.")
    lines.append("")
    lines.append("5) Are there enough opportunities for value investing?")
    lines.append(f"   Total player market cap moved from ${total_start_val:,.0f} to ${total_end_val:,.0f}.")
    lines.append("")
    lines.append("6) Does liquidity remain healthy?")
    lines.append(f"   Average bid/ask spread {liquidity_trend} over the run.")
    lines.append("")
    lines.append("7) Does the Bank become too important?")
    lines.append(f"   Cumulative cash the Bank injected (Quick Sells): ${econ['cumulative_bank_cash_injected'].iloc[-1]:,.0f}. "
                 f"Cumulative cash absorbed (Quick Buys): ${econ['cumulative_bank_cash_absorbed'].iloc[-1]:,.0f}. "
                 f"Bank holds {econ['bank_share_pct_of_supply'].iloc[-1]*100:.1f}% of total share supply at the end.")
    lines.append("")
    lines.append("8) Does ownership become too concentrated?")
    lines.append(f"   Final avg largest-owner stake: {avg_owner_final:.1f}% (max: {max_owner_final:.1f}%). "
                 f"Avg HHI: {hhi_final:.3f}.")
    lines.append("")
    lines.append("9) Does the market remain interesting after many events?")
    lines.append(f"   See ownership_concentration.png / user_wealth_distribution.png for spread over time.")
    lines.append("")
    lines.append("HEALTH CHECK: IS THE ECONOMY STILL FUN / FAIR?")
    lines.append("-" * 55)
    for line in build_health_check_lines(sim, dfs, user_perf_df):
        lines.append(line)
    lines.append("")
    lines.append("NEW HUMAN ENTRANTS")
    lines.append("-" * 55)
    n_entrants = len(sim.entrant_log)
    lines.append(f"   {n_entrants} new humans joined after the initial auction "
                 f"(final humans: {n_humans_final} vs {cfg.num_initial_humans} initial; "
                 f"target was +{cfg.human_entrant_growth_target}).")
    if humans_df is not None and len(humans_df) > 0:
        by_cohort = humans_df.groupby("cohort")["roi_pct"].mean()
        for cohort, roi in by_cohort.items():
            lines.append(f"     - {cohort} avg ROI: {roi:+.1f}%")
    lines.append("")
    lines.append("SIMULATED NEWS")
    lines.append("-" * 55)
    news_by_type = {}
    for e in sim.news_log:
        news_by_type[e["event_type"]] = news_by_type.get(e["event_type"], 0) + 1
    for t, c in sorted(news_by_type.items(), key=lambda kv: -kv[1]):
        lines.append(f"     - {t}: {c}")
    lines.append(f"   Team-switch rumors: {sim.rumor_started_count} started, "
                 f"{sim.rumor_confirmed_count} confirmed, {sim.rumor_debunked_count} debunked.")
    lines.append(f"   Player retirements (rookie replacements): {sim.retirement_count}")
    lines.append("")
    lines.append("ELO (investing skill, separate from wealth)")
    lines.append("-" * 55)
    if elo_df is not None and len(elo_df) > 0:
        last = elo_df.iloc[-1]
        gap = last['avg_human_elo'] - last['avg_bot_elo']
        lines.append(f"   Final avg human ELO: {last['avg_human_elo']:.0f} "
                     f"(range {last['min_human_elo']:.0f}-{last['max_human_elo']:.0f}); "
                     f"avg bot ELO: {last['avg_bot_elo']:.0f} (gap: {gap:+.0f}). Humans and bots draw "
                     f"from the same strategy distribution, so this gap should be small/noise-level, "
                     f"not a systematic edge either way.")
    if humans_df is not None and len(humans_df) > 0:
        top_elo = humans_df.sort_values("elo", ascending=False).head(3)
        for _, row in top_elo.iterrows():
            lines.append(f"     - user {row['user_id']} ({row['strategy']}): ELO {row['elo']:.0f}, "
                         f"ROI {row['roi_pct']:+.1f}%")
    lines.append("")
    lines.append("SUCCESS CRITERIA")
    lines.append("-" * 55)
    checks = success_criteria.evaluate_run(sim, dfs, user_perf_df)
    lines.append(success_criteria.format_report(checks))
    lines.append("")
    lines.append("All raw series are in the accompanying *_metrics.csv files for further analysis.")

    text = "\n".join(lines)
    with open(os.path.join(out_dir, "summary_report.txt"), "w") as f:
        f.write(text)
    return text
