"""
Entry point for the Forecast economy simulator.

Usage:
    python main.py                       # run with default config (spec v2 scale)
    python main.py --tournaments 50      # override total event count (cash cups adjust)
    python main.py --quick               # small/fast smoke-test run
    python main.py --dividend-tier aggressive --transaction-fee 0.005 --bank-spread 0.05

Outputs are written to `output/<run_name>/`:
    *.csv               -- one file per metrics category, plus the raw
                            per-tournament price history and per-user
                            performance (ROI, ELO, turnover)
    *.png                -- charts
    auction_summary.csv
    news_log.csv          -- every simulated news event fired during the run
    summary_report.txt    -- plain-English answers to the spec's "Goals of
                            Simulation" + "Success Metrics" questions
"""

import argparse
import os
import time

import numpy as np
import pandas as pd

from forecast_sim.config import SimConfig, DIVIDEND_POOL_TIERS
from forecast_sim.simulator import Simulator
from forecast_sim.visualize import generate_all_charts
from forecast_sim import success_criteria


def parse_args():
    ap = argparse.ArgumentParser(description="Forecast economy simulator")
    ap.add_argument("--players", type=int, default=None)
    ap.add_argument("--humans", type=int, default=None, help="initial human count")
    ap.add_argument("--bots", type=int, default=None, help="permanent bot count")
    ap.add_argument("--human-growth", type=int, default=None, help="humans added over the season")
    ap.add_argument("--tournaments", type=int, default=None, help="total events; cash-cup count adjusts")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--payout-curve", type=str, choices=["exponential", "power"], default=None)
    ap.add_argument("--dividend-tier", type=str, choices=list(DIVIDEND_POOL_TIERS.keys()), default=None)
    ap.add_argument("--transaction-fee", type=float, default=None)
    ap.add_argument("--bank-spread", type=float, default=None)
    ap.add_argument("--out", type=str, default=None, help="output directory")
    ap.add_argument("--quick", action="store_true", help="small fast smoke-test run")
    return ap.parse_args()


def build_config(args) -> SimConfig:
    cfg = SimConfig()
    if args.quick:
        cfg.num_players = 40
        cfg.num_initial_humans = 10
        cfg.num_bots = 30
        cfg.human_entrant_growth_target = 15
        cfg.cash_cup_count = 10
        cfg.fncs_count = 2
        cfg.global_count = 1
    if args.players:
        cfg.num_players = args.players
    if args.humans:
        cfg.num_initial_humans = args.humans
    if args.bots:
        cfg.num_bots = args.bots
    if args.human_growth is not None:
        cfg.human_entrant_growth_target = args.human_growth
    if args.tournaments:
        # Preserve the FNCS/Global finale, scale the Cash Cup count to hit
        # the requested total.
        cfg.cash_cup_count = max(1, args.tournaments - cfg.fncs_count - cfg.global_count)
    if args.seed is not None:
        cfg.random_seed = args.seed
    if args.payout_curve:
        cfg.payout_curve = args.payout_curve
    if args.dividend_tier:
        cfg.dividend_pool_tier = args.dividend_tier
    if args.transaction_fee is not None:
        cfg.transaction_fee_rate = args.transaction_fee
    if args.bank_spread is not None:
        cfg.bank_spread = args.bank_spread
    if args.out:
        cfg.output_dir = args.out
    return cfg


def write_csvs(dfs, auction_summary, news_log, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    for name, df in dfs.items():
        df.to_csv(os.path.join(out_dir, f"{name}_metrics.csv"), index=False)
    pd.DataFrame(auction_summary).to_csv(os.path.join(out_dir, "auction_summary.csv"), index=False)
    pd.DataFrame(news_log).to_csv(os.path.join(out_dir, "news_log.csv"), index=False)


def _user_trade_stats(user):
    notional = 0.0
    count = 0
    for rec in user.transaction_history:
        if rec.get("action") in ("buy_fill", "sell_fill", "quick_buy_bank", "quick_sell_bank"):
            notional += rec.get("qty", 0) * rec.get("price", 0.0)
            count += 1
    return notional, count


def write_user_performance(sim: Simulator, out_dir):
    escrow_by_user = sim.market.escrowed_cash_by_user()
    rows = []
    for u in sim.users:
        nw = u.net_worth(lambda pid: sim.market.current_price(pid)) + escrow_by_user.get(u.user_id, 0.0)
        roi = (nw - u.starting_cash_at_join) / u.starting_cash_at_join * 100
        notional, trade_count = _user_trade_stats(u)
        turnover = notional / u.starting_cash_at_join if u.starting_cash_at_join else 0.0
        rows.append({
            "user_id": u.user_id,
            "is_bot": u.is_bot,
            "strategy": u.strategy,
            "cohort": "original" if u.joined_tournament == 0 else "new_entrant",
            "joined_tournament": u.joined_tournament,
            "tournaments_active": sim.cfg.num_tournaments - u.joined_tournament,
            "starting_cash": u.starting_cash_at_join,
            "final_cash": u.cash,
            "final_net_worth": nw,
            "roi_pct": roi,
            "elo": u.elo,
            "trade_count": trade_count,
            "trade_notional": notional,
            "turnover_x_starting_cash": turnover,
            "is_passive_holder": trade_count <= 2,
        })
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out_dir, "user_performance.csv"), index=False)
    return df


def build_health_check_lines(sim: Simulator, dfs, user_perf_df):
    econ = dfs["economy"]
    mkt = dfs["market"]
    users_df = dfs["users"]
    players_df = dfs["players"]
    prices_df = dfs["price_history"]
    lines = []

    lines.append("1) Are dividends still meaningful?")
    div_yield = econ["dividends_paid_this_round"] / econ["total_market_cap"].replace(0, np.nan)
    y0 = div_yield.iloc[:10].mean() * 100
    y1 = div_yield.iloc[-10:].mean() * 100
    lines.append(f"   Dividends paid per event, as a % of total market cap: {y0:.2f}% (first 10) vs "
                 f"{y1:.2f}% (last 10). {'Holding steady/growing' if y1 >= y0 else 'Fading'}.")
    lines.append("")

    lines.append("2) Can new (human) users compete?")
    humans = user_perf_df[~user_perf_df["is_bot"]] if user_perf_df is not None else None
    if humans is not None and len(humans) > 0:
        orig = humans[humans["cohort"] == "original"]
        ent = humans[humans["cohort"] == "new_entrant"]
        top10 = humans.sort_values("final_net_worth", ascending=False).head(10)
        n_entrants_top10 = int((top10["cohort"] == "new_entrant").sum())
        lines.append(f"   By raw net worth: {n_entrants_top10}/10 of the top-10 richest HUMANS are new entrants.")
        if len(ent) > 0:
            lines.append(f"   By ROI: original-cohort avg {orig['roi_pct'].mean():+.1f}% vs "
                         f"new-entrant avg {ent['roi_pct'].mean():+.1f}%.")
    lines.append("")

    lines.append("3) Is trading volume healthy?")
    v0 = mkt["trading_volume_shares"].iloc[:10].mean()
    v1 = mkt["trading_volume_shares"].iloc[-10:].mean()
    lines.append(f"   Avg shares traded/event: {v0:,.0f} (first 10) vs {v1:,.0f} (last 10).")
    lines.append("")

    lines.append("4) Are there still opportunities to find undervalued players?")
    if humans is not None and len(humans) > 0:
        by_strat = humans.groupby("strategy")["roi_pct"].mean().sort_values(ascending=False)
        best3 = ", ".join(f"{s} ({v:+.1f}%)" for s, v in by_strat.head(3).items())
        lines.append(f"   Top human strategies by avg ROI: {best3}.")
    final_t, first_t = prices_df["tournament"].max(), prices_df["tournament"].min()
    p_first = prices_df[prices_df["tournament"] == first_t].sort_values("price", ascending=False)
    p_last = prices_df[prices_df["tournament"] == final_t].sort_values("price", ascending=False)
    overlap = len(set(p_first["player_id"].iloc[:10]) & set(p_last["player_id"].iloc[:10]))
    lines.append(f"   Price-leaderboard top 10 overlap, first vs. last event: {overlap}/10.")
    lines.append("")

    lines.append("5) Is the leaderboard still changing?")
    n_changes_user = int((users_df["top_user_id"].diff() != 0).sum())
    n_changes_player = int((players_df["highest_valued_player_id"].diff() != 0).sum())
    lines.append(f"   Richest-user leaderboard changed hands {n_changes_user} times; "
                 f"highest-valued-player leaderboard changed {n_changes_player} times.")
    lines.append("")

    lines.append("6) Can poorer players still perform and keep a high ROI?")
    if humans is not None and len(humans) > 0:
        orig = humans[humans["cohort"] == "original"]
        n_losers = int((orig["roi_pct"] < 0).sum())
        lines.append(f"   Among original humans, {n_losers}/{len(orig)} ended with negative ROI "
                     f"(range {orig['roi_pct'].min():+.1f}% to {orig['roi_pct'].max():+.1f}%).")

    return lines


def main():
    args = parse_args()
    cfg = build_config(args)

    run_name = time.strftime("run_%Y%m%d_%H%M%S")
    out_dir = os.path.join(cfg.output_dir, run_name)
    os.makedirs(out_dir, exist_ok=True)

    print(f"Starting simulation: {cfg.num_players} players, {cfg.num_initial_humans} initial humans "
          f"(+{cfg.human_entrant_growth_target} over the season), {cfg.num_bots} permanent bots, "
          f"{cfg.num_tournaments} events ({cfg.cash_cup_count} Cash Cups / {cfg.fncs_count} FNCS / "
          f"{cfg.global_count} Global), dividend tier={cfg.dividend_pool_tier}, "
          f"transaction fee={cfg.transaction_fee_rate*100:.2f}%, bank spread={cfg.bank_spread*100:.0f}%")
    print(f"Output directory: {out_dir}")

    sim = Simulator(cfg)
    sim.setup()
    print("Initial auction complete.")

    dfs = sim.run()
    print("Simulation complete. Writing outputs...")

    write_csvs(dfs, sim.auction_summary, sim.news_log, out_dir)
    user_perf_df = write_user_performance(sim, out_dir)
    chart_paths = generate_all_charts(dfs, sim.players, out_dir, user_perf_df)
    for p in chart_paths:
        print(f"  chart -> {p}")

    from forecast_sim.report import build_summary_report
    summary = build_summary_report(sim, dfs, user_perf_df, out_dir, build_health_check_lines)
    print()
    print(summary)
    print()
    print(f"All outputs written to {out_dir}")


if __name__ == "__main__":
    main()
