"""
100-run batch: tests whether the permanent bot population behaves like an
equivalent slice of humans (no systematic ELO/ROI edge in either
direction), and how the broader economy holds up, across variations in:

  - population-wide strategy mix (5 variants, applied identically to
    humans AND bots -- see config.py's note on why they share one
    distribution)
  - bot:human ratio (4 variants: spec default 300 bots, bot-light 100,
    bot-heavy 500, and a 1:1-ish 200)
  - random seed (5 per combination, for sampling variance)

5 x 4 x 5 = 100 full-scale runs (200 players, 40 events, spec population
counts except where the bot-ratio variant overrides num_bots).

For each run, compares ORIGINAL-cohort humans (present since t=0, same
tenure as every bot) against bots directly -- new entrants are excluded
from this specific comparison because they have systematically less time
to compound, which is a real, separate, already-documented effect (see
README "new users can still compete") and would otherwise contaminate a
same-tenure bot-vs-human comparison. All-human (including entrants)
figures are recorded too, for reference.
"""

import argparse
import os
import time
import numpy as np
import pandas as pd

from forecast_sim.config import SimConfig
from forecast_sim.simulator import Simulator
from forecast_sim import success_criteria

OUT_CSV = "symmetry_batch_results.csv"

STRATEGY_MIX_GRID = {
    "default": None,
    "momentum_heavy": {"momentum_trader": 0.35, "scalper": 0.15, "hype_chaser": 0.15,
                        "contrarian": 0.10, "value_investor": 0.10, "index_investor": 0.10,
                        "random": 0.05},
    "fundamentals_heavy": {"value_investor": 0.30, "dividend_hunter": 0.25, "smart_money": 0.20,
                            "index_investor": 0.15, "news_trader": 0.10},
    "chaos_heavy": {"random": 0.25, "panic_seller": 0.25, "hype_chaser": 0.25,
                     "speculator": 0.15, "scalper": 0.10},
    "liquidity_heavy": {"liquidity_provider": 0.35, "index_investor": 0.25, "value_investor": 0.15,
                         "team_loyalist": 0.15, "contrarian": 0.10},
}

BOT_RATIO_GRID = {
    "spec_default_300bots": 300,
    "bot_light_100bots": 100,
    "bot_heavy_500bots": 500,
    "one_to_one_200bots": 200,
}

SEEDS = [1, 2, 3, 4, 5]


def make_config(strategy_mix_name, num_bots):
    cfg = SimConfig()
    cfg.num_bots = num_bots
    mix = STRATEGY_MIX_GRID[strategy_mix_name]
    if mix is not None:
        cfg.trading_strategy_weights = dict(mix)
    return cfg


def run_one(strategy_mix_name, bot_ratio_name, seed):
    cfg = make_config(strategy_mix_name, BOT_RATIO_GRID[bot_ratio_name])
    cfg.random_seed = seed
    t0 = time.time()
    sim = Simulator(cfg)
    sim.setup()
    dfs = sim.run(progress_every=0)
    elapsed = time.time() - t0

    escrow = sim.market.escrowed_cash_by_user()

    def nw(u):
        return u.net_worth(lambda pid: sim.market.current_price(pid)) + escrow.get(u.user_id, 0.0)

    def roi(u):
        return (nw(u) - u.starting_cash_at_join) / u.starting_cash_at_join * 100

    orig_humans = [u for u in sim.users if not u.is_bot and u.joined_tournament == 0]
    all_humans = [u for u in sim.users if not u.is_bot]
    bots = [u for u in sim.users if u.is_bot]

    orig_elo = np.array([u.elo for u in orig_humans])
    bot_elo = np.array([u.elo for u in bots])
    all_human_elo = np.array([u.elo for u in all_humans])
    orig_roi = np.array([roi(u) for u in orig_humans])
    bot_roi = np.array([roi(u) for u in bots])
    all_human_roi = np.array([roi(u) for u in all_humans])

    econ, mkt, users_df = dfs["economy"], dfs["market"], dfs["users"]
    tail = max(1, len(econ) // 4)

    rows = []
    for u in sim.users:
        rows.append({"user_id": u.user_id, "is_bot": u.is_bot, "strategy": u.strategy,
                     "cohort": "original" if u.joined_tournament == 0 else "new_entrant",
                     "joined_tournament": u.joined_tournament,
                     "tournaments_active": cfg.num_tournaments - u.joined_tournament,
                     "roi_pct": roi(u), "final_net_worth": nw(u)})
    user_perf_df = pd.DataFrame(rows)
    checks = success_criteria.evaluate_run(sim, dfs, user_perf_df)
    n_pass = sum(1 for c in checks if c.verdict == "PASS")

    # pooled standard error for the orig-human-vs-bot ELO gap (Welch-style,
    # unequal sample sizes/variances -- orig humans n=50, bots n=100-500)
    se = float(np.sqrt(orig_elo.var(ddof=1) / len(orig_elo) + bot_elo.var(ddof=1) / len(bot_elo)))
    gap = float(orig_elo.mean() - bot_elo.mean())

    return {
        "strategy_mix": strategy_mix_name,
        "bot_ratio": bot_ratio_name,
        "seed": seed,
        "num_bots": cfg.num_bots,
        "num_orig_humans": len(orig_humans),
        "num_all_humans": len(all_humans),
        "runtime_sec": elapsed,
        "orig_human_elo_mean": float(orig_elo.mean()),
        "bot_elo_mean": float(bot_elo.mean()),
        "all_human_elo_mean": float(all_human_elo.mean()),
        "orig_vs_bot_elo_gap": gap,
        "orig_vs_bot_elo_gap_se": se,
        "orig_vs_bot_elo_gap_z": gap / se if se > 0 else 0.0,
        "orig_human_roi_mean": float(orig_roi.mean()),
        "bot_roi_mean": float(bot_roi.mean()),
        "all_human_roi_mean": float(all_human_roi.mean()),
        "orig_vs_bot_roi_gap": float(orig_roi.mean() - bot_roi.mean()),
        "cash_ratio_final_quarter_avg": float(econ["cash_ratio"].iloc[-tail:].mean()),
        "inflation_pct": float((econ["total_money_supply"].iloc[-1] - sim.post_auction_total_cash)
                                / sim.post_auction_total_cash * 100),
        "trading_volume_pct_mcap_final_quarter_avg": float(mkt["trading_volume_pct_of_market_cap"].iloc[-tail:].mean()),
        "bank_share_pct_final": float(econ["bank_share_pct_of_supply"].iloc[-1]),
        "gini_humans_final": float(users_df["gini_net_worth_humans"].iloc[-1]),
        "success_criteria_pass_count": n_pass,
    }


def all_combos():
    return [(sm, br, seed) for sm in STRATEGY_MIX_GRID for br in BOT_RATIO_GRID for seed in SEEDS]


def main():
    ap = argparse.ArgumentParser(description="100-run bot/human symmetry batch (chunkable)")
    ap.add_argument("--start", type=int, default=0, help="start index into the combo list")
    ap.add_argument("--end", type=int, default=None, help="end index (exclusive); default = all")
    args = ap.parse_args()

    combos = all_combos()
    end = args.end if args.end is not None else len(combos)
    chunk = combos[args.start:end]
    print(f"Running combos [{args.start}:{end}] of {len(combos)} total...")

    write_header = not os.path.exists(OUT_CSV)
    t_start = time.time()
    for i, (sm, br, seed) in enumerate(chunk, start=args.start + 1):
        r = run_one(sm, br, seed)
        row_df = pd.DataFrame([r])
        row_df.to_csv(OUT_CSV, mode="a", header=write_header, index=False)
        write_header = False
        print(f"[{i}/{len(combos)}] mix={sm:20s} ratio={br:20s} seed={seed}  "
              f"elo_gap={r['orig_vs_bot_elo_gap']:+7.1f} (z={r['orig_vs_bot_elo_gap_z']:+.2f})  "
              f"success={r['success_criteria_pass_count']}/7  ({r['runtime_sec']:.1f}s, "
              f"total {time.time()-t_start:.0f}s elapsed)", flush=True)

    print(f"\nChunk done: {len(chunk)} rows appended to {OUT_CSV} in {time.time()-t_start:.0f}s.")


if __name__ == "__main__":
    main()
