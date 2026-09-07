"""
Parameter-sweep experiment runner (spec "Experiments to Run"):

    Transaction fee    (0%, 0.1%, 0.25%, 0.5%, 1%)
    Bank spread        (5%, 10%, 15%)
    Dividend pools     (conservative/baseline/aggressive, ~3.5/5.2/7.8% of economy)
    Bot count          (100, 300, 500)
    New user growth    (50, 150, 300 additional humans over the season)
    Bot strategy mix   (spec default vs. two alternative distributions)
    News frequency      (fewer/spec-default/more events per tournament)

A full cross-product of every value on every axis is combinatorially
enormous and not how you'd actually run this in practice, so this sweeps
ONE axis at a time off a shared baseline config (standard one-factor-at-
a-time sensitivity analysis), plus one small 2D grid over the two levers
that interact directly as money-supply controls (transaction fee x bank
spread). Runs at a reduced-but-still-realistic scale by default (see
SWEEP_SCALE) so the whole suite finishes in a few minutes; use --full-scale
to run every combination at the spec's full 200/500/40 scale instead.

For every run, records the same run-level health metrics the summary
report and success_criteria.py use, plus the success-criteria pass count,
and writes one row per run to experiment_results.csv plus a few
comparison charts.
"""

import argparse
import os
import time

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from forecast_sim.config import (
    SimConfig, TRANSACTION_FEE_GRID, BANK_SPREAD_GRID, DIVIDEND_POOL_GRID,
    BOT_COUNT_GRID, NEW_USER_GROWTH_GRID,
)
from forecast_sim.simulator import Simulator
from forecast_sim import success_criteria

OUT_DIR = "experiment_results"

# Reduced scale for the sweep (keeps the whole suite fast); scales every
# population number down ~2.5x from the spec's full 200/500/40 while
# preserving the same *ratios* (humans:bots:players, cash cups:fncs:global).
SWEEP_SCALE = dict(num_players=80, num_initial_humans=20, num_bots=120,
                    cash_cup_count=14, fncs_count=3, global_count=1)
FULL_SCALE = dict(num_players=200, num_initial_humans=50, num_bots=300,
                   cash_cup_count=36, fncs_count=3, global_count=1)

# Alternative population-wide strategy mixes (applied identically to
# humans AND bots -- see config.py's note on why the two populations
# share one distribution) to compare against the default roster.
STRATEGY_MIX_GRID = {
    "default": None,  # None = leave cfg.trading_strategy_weights at its default
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

# News frequency variants (spec default is 2-3/event).
NEWS_FREQUENCY_GRID = {
    "sparse_1_2": (1, 2),
    "spec_default_2_3": (2, 3),
    "dense_3_5": (3, 5),
}


def make_baseline(scale: dict) -> SimConfig:
    cfg = SimConfig()
    for k, v in scale.items():
        setattr(cfg, k, v)
    return cfg


def run_one(cfg: SimConfig, label: str, axis: str) -> dict:
    t0 = time.time()
    sim = Simulator(cfg)
    sim.setup()
    dfs = sim.run(progress_every=0)
    elapsed = time.time() - t0

    econ, mkt, users = dfs["economy"], dfs["market"], dfs["users"]
    tail = max(1, len(econ) // 4)

    # Build a user_performance-shaped frame (same columns success_criteria
    # expects) without touching disk.
    escrow_by_user = sim.market.escrowed_cash_by_user()
    rows = []
    for u in sim.users:
        nw = u.net_worth(lambda pid: sim.market.current_price(pid)) + escrow_by_user.get(u.user_id, 0.0)
        rows.append({
            "user_id": u.user_id, "is_bot": u.is_bot, "strategy": u.strategy,
            "cohort": "original" if u.joined_tournament == 0 else "new_entrant",
            "joined_tournament": u.joined_tournament,
            "tournaments_active": cfg.num_tournaments - u.joined_tournament,
            "roi_pct": (nw - u.starting_cash_at_join) / u.starting_cash_at_join * 100,
            "final_net_worth": nw,
        })
    user_perf_df = pd.DataFrame(rows)

    checks = success_criteria.evaluate_run(sim, dfs, user_perf_df)
    n_pass = sum(1 for c in checks if c.verdict == "PASS")

    return {
        "axis": axis,
        "label": label,
        "runtime_sec": elapsed,
        "num_players": cfg.num_players,
        "num_initial_humans": cfg.num_initial_humans,
        "num_bots": cfg.num_bots,
        "num_events": cfg.num_tournaments,
        "human_entrant_growth_target": cfg.human_entrant_growth_target,
        "dividend_pool_tier": cfg.dividend_pool_tier,
        "transaction_fee_rate": cfg.transaction_fee_rate,
        "bank_spread": cfg.bank_spread,
        "cash_ratio_final_quarter_avg": float(econ["cash_ratio"].iloc[-tail:].mean()),
        "inflation_pct": float((econ["total_money_supply"].iloc[-1] - sim.post_auction_total_cash)
                                / sim.post_auction_total_cash * 100),
        "trading_volume_pct_of_mcap_final_quarter_avg": float(mkt["trading_volume_pct_of_market_cap"].iloc[-tail:].mean()),
        "dividends_total": float(econ["dividends_paid_this_round"].sum()),
        "fees_removed_total": float(econ["cumulative_transaction_fees_removed"].iloc[-1]
                                     + econ["cumulative_auction_fees_removed"].iloc[-1]),
        "bank_share_pct_final": float(econ["bank_share_pct_of_supply"].iloc[-1]),
        "gini_net_worth_humans_final": float(users["gini_net_worth_humans"].iloc[-1]),
        "final_human_count": sum(1 for u in sim.users if not u.is_bot),
        "success_criteria_pass_count": n_pass,
        "success_criteria_total": len(checks),
    }


def sweep_transaction_fee(baseline_scale):
    out = []
    for fee in TRANSACTION_FEE_GRID:
        cfg = make_baseline(baseline_scale)
        cfg.transaction_fee_rate = fee
        out.append(run_one(cfg, f"fee={fee*100:.2f}%", "transaction_fee"))
    return out


def sweep_bank_spread(baseline_scale):
    out = []
    for spread in BANK_SPREAD_GRID:
        cfg = make_baseline(baseline_scale)
        cfg.bank_spread = spread
        out.append(run_one(cfg, f"spread={spread*100:.0f}%", "bank_spread"))
    return out


def sweep_dividend_pool(baseline_scale):
    out = []
    for tier in DIVIDEND_POOL_GRID:
        cfg = make_baseline(baseline_scale)
        cfg.dividend_pool_tier = tier
        out.append(run_one(cfg, tier, "dividend_pool"))
    return out


def sweep_bot_count(baseline_scale):
    out = []
    for n_bots in BOT_COUNT_GRID:
        cfg = make_baseline(baseline_scale)
        cfg.num_bots = n_bots
        out.append(run_one(cfg, f"bots={n_bots}", "bot_count"))
    return out


def sweep_new_user_growth(baseline_scale):
    out = []
    for growth in NEW_USER_GROWTH_GRID:
        cfg = make_baseline(baseline_scale)
        cfg.human_entrant_growth_target = growth
        out.append(run_one(cfg, f"+{growth} humans", "new_user_growth"))
    return out


def sweep_strategy_mix(baseline_scale):
    out = []
    for name, mix in STRATEGY_MIX_GRID.items():
        cfg = make_baseline(baseline_scale)
        if mix is not None:
            cfg.trading_strategy_weights = dict(mix)
        out.append(run_one(cfg, name, "population_strategy_mix"))
    return out


def sweep_news_frequency(baseline_scale):
    out = []
    for name, (lo, hi) in NEWS_FREQUENCY_GRID.items():
        cfg = make_baseline(baseline_scale)
        cfg.news_events_per_tournament_min = lo
        cfg.news_events_per_tournament_max = hi
        out.append(run_one(cfg, name, "news_frequency"))
    return out


def grid_fee_x_spread(baseline_scale):
    out = []
    for fee in TRANSACTION_FEE_GRID:
        for spread in BANK_SPREAD_GRID:
            cfg = make_baseline(baseline_scale)
            cfg.transaction_fee_rate = fee
            cfg.bank_spread = spread
            out.append(run_one(cfg, f"fee={fee*100:.2f}%,spread={spread*100:.0f}%", "fee_x_spread_grid"))
    return out


def main():
    ap = argparse.ArgumentParser(description="Forecast economy parameter sweep")
    ap.add_argument("--full-scale", action="store_true",
                     help="run every combination at the spec's full 200/500/40 scale (slow)")
    args = ap.parse_args()
    scale = FULL_SCALE if args.full_scale else SWEEP_SCALE

    os.makedirs(OUT_DIR, exist_ok=True)
    results = []
    for fn in (sweep_transaction_fee, sweep_bank_spread, sweep_dividend_pool, sweep_bot_count,
               sweep_new_user_growth, sweep_strategy_mix, sweep_news_frequency):
        print(f"--- {fn.__name__} ---")
        rows = fn(scale)
        for r in rows:
            print(f"    {r['label']:20s} success={r['success_criteria_pass_count']}/{r['success_criteria_total']} "
                  f"cash_ratio={r['cash_ratio_final_quarter_avg']*100:5.1f}% "
                  f"inflation={r['inflation_pct']:7.1f}% "
                  f"volume%mcap={r['trading_volume_pct_of_mcap_final_quarter_avg']*100:.3f}% "
                  f"gini={r['gini_net_worth_humans_final']:.3f} "
                  f"({r['runtime_sec']:.1f}s)")
        results.extend(rows)

    print("--- grid_fee_x_spread ---")
    grid_rows = grid_fee_x_spread(scale)
    results.extend(grid_rows)

    df = pd.DataFrame(results)
    df.to_csv(os.path.join(OUT_DIR, "experiment_results.csv"), index=False)

    # ---- identify the best combination per axis (max success-criteria passes,
    # tie-broken by cash ratio closeness to the 15-30% midpoint) ----
    best_lines = ["BEST COMBINATION PER AXIS (by success-criteria pass count)", "=" * 60]
    for axis in df["axis"].unique():
        sub = df[df["axis"] == axis].copy()
        sub["cash_ratio_dist"] = (sub["cash_ratio_final_quarter_avg"] - 0.225).abs()
        sub = sub.sort_values(["success_criteria_pass_count", "cash_ratio_dist"], ascending=[False, True])
        best = sub.iloc[0]
        best_lines.append(f"[{axis}] best = {best['label']} "
                          f"({best['success_criteria_pass_count']}/{best['success_criteria_total']} pass, "
                          f"cash_ratio={best['cash_ratio_final_quarter_avg']*100:.1f}%, "
                          f"inflation={best['inflation_pct']:+.1f}%)")

    text = "\n".join(best_lines)
    with open(os.path.join(OUT_DIR, "experiment_summary.txt"), "w") as f:
        f.write(text)
    print()
    print(text)

    # ---- comparison chart: success-criteria pass count per axis value ----
    axes_list = [a for a in df["axis"].unique() if a != "fee_x_spread_grid"]
    fig, ax_grid = plt.subplots(len(axes_list), 1, figsize=(9, 3.2 * len(axes_list)))
    if len(axes_list) == 1:
        ax_grid = [ax_grid]
    for ax, axis in zip(ax_grid, axes_list):
        sub = df[df["axis"] == axis]
        ax.bar(sub["label"], sub["success_criteria_pass_count"], color="#2563eb")
        ax.set_title(f"Success-criteria passes by {axis}")
        ax.set_ylabel("# criteria passing (of 7)")
        ax.tick_params(axis="x", rotation=20)
        ax.grid(alpha=0.3, axis="y")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT_DIR, "experiment_success_by_axis.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)

    # ---- heatmap: fee x spread -> success-criteria pass count ----
    pivot = grid_rows_to_pivot(grid_rows)
    fig, ax = plt.subplots(figsize=(7, 5))
    im = ax.imshow(pivot.values, cmap="RdYlGn", vmin=0, vmax=7)
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels([f"{c*100:.0f}%" for c in pivot.columns])
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels([f"{r*100:.2f}%" for r in pivot.index])
    ax.set_xlabel("Bank spread")
    ax.set_ylabel("Transaction fee")
    ax.set_title("Success-criteria passes: transaction fee x bank spread")
    for i in range(len(pivot.index)):
        for j in range(len(pivot.columns)):
            ax.text(j, i, int(pivot.values[i, j]), ha="center", va="center")
    fig.colorbar(im, ax=ax, label="# criteria passing (of 7)")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT_DIR, "experiment_fee_x_spread_heatmap.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)

    print(f"\nAll outputs written to {OUT_DIR}/")


def grid_rows_to_pivot(grid_rows):
    df = pd.DataFrame(grid_rows)
    return df.pivot(index="transaction_fee_rate", columns="bank_spread", values="success_criteria_pass_count")


if __name__ == "__main__":
    main()
