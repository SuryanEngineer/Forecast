"""
Experiment: tests the liquidity-stall concern directly.

Scenario A - "cash-starved auction, no rescue": auction spend fraction is
    pushed very high (97%) so almost all user cash converts into share
    ownership at t=0, and new entrants are disabled. Expect: trading
    volume collapses early, Bank ends up holding a growing share of
    inventory (nobody has cash to Quick Buy from it), spreads widen.

Scenario B - same cash-starved auction, but new entrants ARE enabled at
    default rate/size. Expect: periodic $1M cash injections from new
    users should un-stick the market -- volume should recover in bursts
    around entrant arrivals.

Scenario C - "too much liquidity": auction spend fraction is pushed very
    low (25%) so most cash sits idle post-auction and prices start low
    relative to available cash. No new entrants (baseline for D).

Scenario D - same low auction spend, but with new entrants arriving MORE
    often and at LARGER size (a bigger fresh-capital multiplier), to see
    what happens when you pour more fuel onto an already cash-rich market.
"""

import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from forecast_sim.config import SimConfig
from forecast_sim.simulator import Simulator

OUT_DIR = "liquidity_experiment"
os.makedirs(OUT_DIR, exist_ok=True)


def run_scenario(name, **overrides):
    cfg = SimConfig()
    for k, v in overrides.items():
        setattr(cfg, k, v)
    print(f"--- running scenario: {name} ---")
    sim = Simulator(cfg)
    sim.setup()
    dfs = sim.run(progress_every=0)
    econ = dfs["economy"]
    mkt = dfs["market"]
    econ = econ.merge(mkt, on="tournament")
    econ["scenario"] = name
    print(f"    final users={len(sim.users)}  final bank_share_pct={econ['bank_share_pct_of_supply'].iloc[-1]:.3f}  "
          f"final volume={econ['trading_volume_shares'].iloc[-1]}  post_auction_cash=${sim.post_auction_total_cash:,.0f}")
    return econ, sim


def main():
    results = {}
    sims = {}

    results["A_stall_no_entrants"], sims["A"] = run_scenario(
        "A_stall_no_entrants",
        auction_spend_fraction=0.97, auction_spend_cap_fraction=1.0,
        enable_new_entrants=False,
    )
    results["B_stall_with_entrants"], sims["B"] = run_scenario(
        "B_stall_with_entrants",
        auction_spend_fraction=0.97, auction_spend_cap_fraction=1.0,
        enable_new_entrants=True,
    )
    results["C_surplus_no_entrants"], sims["C"] = run_scenario(
        "C_surplus_no_entrants",
        auction_spend_fraction=0.25,
        enable_new_entrants=False,
    )
    results["D_surplus_big_entrants"], sims["D"] = run_scenario(
        "D_surplus_big_entrants",
        auction_spend_fraction=0.25,
        enable_new_entrants=True,
        human_entrant_growth_target=400,  # much faster-paced entry than default 150
        new_entrant_whale_prob=0.25,
        new_entrant_whale_cash_multiplier=15.0,
    )
    # Severe versions: auction takes nearly everything AND the dividend
    # pool is tiny (so dividends can't quickly refill cash on their own)
    # -- isolates whether the market can genuinely seize up, and whether
    # entrants are what un-sticks it.
    results["E_severe_stall_no_entrants"], sims["E"] = run_scenario(
        "E_severe_stall_no_entrants",
        auction_spend_fraction=0.99, auction_spend_cap_fraction=1.0,
        dividend_pool_override={"cash_cup": 50_000.0, "fncs": 50_000.0, "global": 50_000.0},
        enable_new_entrants=False,
    )
    results["F_severe_stall_with_entrants"], sims["F"] = run_scenario(
        "F_severe_stall_with_entrants",
        auction_spend_fraction=0.99, auction_spend_cap_fraction=1.0,
        dividend_pool_override={"cash_cup": 50_000.0, "fncs": 50_000.0, "global": 50_000.0},
        enable_new_entrants=True,
    )

    all_df = pd.concat(results.values(), ignore_index=True)
    all_df.to_csv(os.path.join(OUT_DIR, "liquidity_experiment_metrics.csv"), index=False)

    # ---------------- comparison charts ----------------
    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    colors = {"A_stall_no_entrants": "#dc2626", "B_stall_with_entrants": "#16a34a",
              "C_surplus_no_entrants": "#2563eb", "D_surplus_big_entrants": "#7c3aed",
              "E_severe_stall_no_entrants": "#991b1b", "F_severe_stall_with_entrants": "#065f46"}

    for name, df in results.items():
        axes[0, 0].plot(df["tournament"], df["trading_volume_shares"].rolling(3, min_periods=1).mean(),
                         label=name, color=colors[name])
    axes[0, 0].set_title("Trading Volume (3-tournament rolling avg)")
    axes[0, 0].set_xlabel("Tournament #")
    axes[0, 0].set_ylabel("Shares traded")
    axes[0, 0].legend(fontsize=7)
    axes[0, 0].grid(alpha=0.3)

    for name, df in results.items():
        axes[0, 1].plot(df["tournament"], df["total_user_cash"], label=name, color=colors[name])
    axes[0, 1].set_title("Total Liquid User Cash")
    axes[0, 1].set_xlabel("Tournament #")
    axes[0, 1].set_ylabel("$")
    axes[0, 1].legend(fontsize=7)
    axes[0, 1].grid(alpha=0.3)

    for name, df in results.items():
        axes[1, 0].plot(df["tournament"], df["bank_share_pct_of_supply"] * 100, label=name, color=colors[name])
    axes[1, 0].set_title("Bank Share of Total Supply (%)")
    axes[1, 0].set_xlabel("Tournament #")
    axes[1, 0].set_ylabel("%")
    axes[1, 0].legend(fontsize=7)
    axes[1, 0].grid(alpha=0.3)

    for name, df in results.items():
        axes[1, 1].plot(df["tournament"], df["num_users"], label=name, color=colors[name])
    axes[1, 1].set_title("Active Users Over Time")
    axes[1, 1].set_xlabel("Tournament #")
    axes[1, 1].set_ylabel("# users")
    axes[1, 1].legend(fontsize=7)
    axes[1, 1].grid(alpha=0.3)

    fig.tight_layout()
    fig.savefig(os.path.join(OUT_DIR, "liquidity_experiment_comparison.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)

    # ---------------- text summary ----------------
    lines = []
    lines.append("LIQUIDITY STRESS-TEST: does a cash-hungry auction stall the market,")
    lines.append("and do new entrants fix it? (default-scale spec run: 200 players / "
                 "50 initial humans + 300 bots / 40 events)")
    lines.append("=" * 78)
    for name, df in results.items():
        n_events = sims[name[0]].cfg.num_tournaments
        first_10 = df[df["tournament"] <= 10]["trading_volume_shares"].mean()
        last_10 = df[df["tournament"] > max(10, n_events - 10)]["trading_volume_shares"].mean()
        sim = sims[name[0]]
        lines.append("")
        lines.append(f"[{name}]")
        n_participants_t0 = sim.cfg.num_initial_humans + sim.cfg.num_bots
        lines.append(f"  post-auction user cash: ${sim.post_auction_total_cash:,.0f} "
                     f"(of ${n_participants_t0 * sim.cfg.starting_cash:,.0f} starting)")
        lines.append(f"  avg trading volume, events 1-10:  {first_10:,.0f} shares")
        lines.append(f"  avg trading volume, last 10 events: {last_10:,.0f} shares")
        lines.append(f"  final Bank share of supply: {df['bank_share_pct_of_supply'].iloc[-1]*100:.1f}%")
        n_participants_t0 = sim.cfg.num_initial_humans + sim.cfg.num_bots
        lines.append(f"  final users: {len(sim.users)} (started with {n_participants_t0})")
        lines.append(f"  final avg bid/ask spread: {df['avg_bid_ask_spread'].dropna().iloc[-1]:.4f}" if
                     df['avg_bid_ask_spread'].dropna().shape[0] else "  final avg bid/ask spread: n/a")
        early_vols = df[df["tournament"] <= 15]["trading_volume_shares"].tolist()
        lines.append(f"  volume, tournaments 1-15: {early_vols}")

    text = "\n".join(lines)
    with open(os.path.join(OUT_DIR, "liquidity_experiment_summary.txt"), "w") as f:
        f.write(text)
    print()
    print(text)


if __name__ == "__main__":
    main()
