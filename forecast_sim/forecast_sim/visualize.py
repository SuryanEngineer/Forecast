"""
Generates the chart set requested in the spec:
  - Market cap over time
  - Share prices over time
  - User wealth distribution
  - Dividend generation
  - Trading volume
  - Ownership concentration
"""

import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def _save(fig, out_dir, filename):
    path = os.path.join(out_dir, filename)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_market_cap_over_time(dfs, out_dir):
    df = dfs["economy"]
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(df["tournament"], df["total_market_cap"], label="Total market cap", color="#2563eb")
    ax.plot(df["tournament"], df["total_money_supply"], label="Total money supply (cash + escrow)", color="#16a34a")
    ax.set_xlabel("Tournament #")
    ax.set_ylabel("$")
    ax.set_title("Market Capitalization & Money Supply Over Time")
    ax.legend()
    ax.grid(alpha=0.3)
    return _save(fig, out_dir, "market_cap_over_time.png")


def plot_share_prices_over_time(dfs, players, out_dir, top_n=12):
    df = dfs["price_history"]
    fig, ax = plt.subplots(figsize=(9, 5))
    # pick a spread of players by final price: top few, a few mid, a few low
    final = df[df["tournament"] == df["tournament"].max()]
    final = final.sort_values("price", ascending=False)
    chosen = list(final["player_id"].iloc[:top_n // 2]) + \
             list(final["player_id"].iloc[-(top_n - top_n // 2):])
    name_lookup = {p.player_id: p.name for p in players}
    for pid in chosen:
        sub = df[df["player_id"] == pid]
        ax.plot(sub["tournament"], sub["price"], label=name_lookup.get(pid, str(pid)), linewidth=1.2)
    ax.set_xlabel("Tournament #")
    ax.set_ylabel("Share price ($)")
    ax.set_title(f"Share Prices Over Time (top/bottom {top_n} by final price)")
    ax.legend(fontsize=7, ncol=2, loc="upper left")
    ax.grid(alpha=0.3)
    return _save(fig, out_dir, "share_prices_over_time.png")


def plot_user_wealth_distribution(dfs, out_dir):
    df = dfs["users"]
    fig, axes = plt.subplots(1, 2, figsize=(11, 5))

    axes[0].plot(df["tournament"], df["mean_net_worth"], label="Mean", color="#2563eb")
    axes[0].plot(df["tournament"], df["median_net_worth"], label="Median", color="#f59e0b")
    axes[0].fill_between(df["tournament"], df["min_net_worth"], df["max_net_worth"],
                          color="#94a3b8", alpha=0.25, label="Min-Max range")
    axes[0].set_xlabel("Tournament #")
    axes[0].set_ylabel("Net worth ($)")
    axes[0].set_title("User Net Worth Over Time")
    axes[0].legend(fontsize=8)
    axes[0].grid(alpha=0.3)

    axes[1].plot(df["tournament"], df["top_user_net_worth"], label="Top user", color="#16a34a")
    axes[1].plot(df["tournament"], df["bottom_user_net_worth"], label="Bottom user", color="#dc2626")
    axes[1].set_xlabel("Tournament #")
    axes[1].set_ylabel("Net worth ($)")
    axes[1].set_title("Top vs Bottom User Net Worth")
    axes[1].legend(fontsize=8)
    axes[1].grid(alpha=0.3)

    fig.tight_layout()
    return _save(fig, out_dir, "user_wealth_distribution.png")


def plot_dividend_generation(dfs, out_dir):
    df = dfs["economy"]
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.bar(df["tournament"], df["dividends_paid_this_round"], color="#7c3aed", alpha=0.8)
    ax.plot(df["tournament"], df["dividends_paid_this_round"].cumsum() / max(1, len(df)),
            color="#f59e0b", linestyle="--", label="Cumulative avg (scaled)")
    ax.set_xlabel("Tournament #")
    ax.set_ylabel("Dividends paid ($)")
    ax.set_title("Dividend Generation Per Tournament")
    ax.grid(alpha=0.3)
    return _save(fig, out_dir, "dividend_generation.png")


def plot_trading_volume(dfs, out_dir):
    df = dfs["market"]
    fig, axes = plt.subplots(1, 2, figsize=(11, 5))
    axes[0].bar(df["tournament"], df["trading_volume_shares"], color="#0891b2")
    axes[0].set_xlabel("Tournament #")
    axes[0].set_ylabel("Shares traded")
    axes[0].set_title("Trading Volume (shares) Per Tournament")
    axes[0].grid(alpha=0.3)

    axes[1].plot(df["tournament"], df["avg_bid_ask_spread"], color="#be123c")
    axes[1].set_xlabel("Tournament #")
    axes[1].set_ylabel("Avg bid/ask spread (fraction)")
    axes[1].set_title("Average Bid/Ask Spread Over Time")
    axes[1].grid(alpha=0.3)

    fig.tight_layout()
    return _save(fig, out_dir, "trading_volume.png")


def plot_ownership_concentration(dfs, out_dir):
    df = dfs["ownership"]
    fig, axes = plt.subplots(1, 2, figsize=(11, 5))
    axes[0].plot(df["tournament"], df["avg_largest_owner_pct"] * 100, color="#2563eb", label="Avg largest owner %")
    axes[0].plot(df["tournament"], df["max_largest_owner_pct"] * 100, color="#dc2626", label="Max largest owner %")
    axes[0].set_xlabel("Tournament #")
    axes[0].set_ylabel("% of shares")
    axes[0].set_title("Largest Ownership Stake Over Time")
    axes[0].legend(fontsize=8)
    axes[0].grid(alpha=0.3)

    axes[1].plot(df["tournament"], df["avg_ownership_hhi"], color="#7c3aed")
    axes[1].set_xlabel("Tournament #")
    axes[1].set_ylabel("Avg Herfindahl-Hirschman Index")
    axes[1].set_title("Ownership Concentration (HHI, avg across players)")
    axes[1].grid(alpha=0.3)

    fig.tight_layout()
    return _save(fig, out_dir, "ownership_concentration.png")


def plot_liquidity_health(dfs, out_dir):
    """Diagnoses the 'auction drains cash, market stalls' failure mode:
    liquid cash, Bank share inventory (% of supply), and user count over
    time, plus trading volume so a stall (volume -> ~0) is visible
    alongside its cause (cash -> ~0 and/or Bank holding most shares)."""
    econ = dfs["economy"]
    mkt = dfs["market"]
    fig, axes = plt.subplots(2, 2, figsize=(12, 9))

    axes[0, 0].plot(econ["tournament"], econ["total_user_cash"], color="#16a34a")
    axes[0, 0].set_title("Total Liquid User Cash")
    axes[0, 0].set_xlabel("Tournament #")
    axes[0, 0].set_ylabel("$")
    axes[0, 0].grid(alpha=0.3)

    axes[0, 1].plot(econ["tournament"], econ["bank_share_pct_of_supply"] * 100, color="#dc2626")
    axes[0, 1].set_title("Shares Held by the Bank (% of total supply)")
    axes[0, 1].set_xlabel("Tournament #")
    axes[0, 1].set_ylabel("%")
    axes[0, 1].grid(alpha=0.3)

    axes[1, 0].bar(mkt["tournament"], mkt["trading_volume_shares"], color="#0891b2")
    axes[1, 0].set_title("Trading Volume (shares/tournament)")
    axes[1, 0].set_xlabel("Tournament #")
    axes[1, 0].set_ylabel("Shares traded")
    axes[1, 0].grid(alpha=0.3)

    axes[1, 1].plot(econ["tournament"], econ["num_users"], color="#7c3aed")
    axes[1, 1].set_title("Active Users (original + new entrants)")
    axes[1, 1].set_xlabel("Tournament #")
    axes[1, 1].set_ylabel("# users")
    axes[1, 1].grid(alpha=0.3)

    fig.tight_layout()
    return _save(fig, out_dir, "liquidity_health.png")


def plot_strategy_performance(user_perf_df, out_dir):
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    by_strategy = user_perf_df.groupby("strategy")["roi_pct"].mean().sort_values()
    axes[0].barh(by_strategy.index, by_strategy.values, color="#2563eb")
    axes[0].set_xlabel("Avg ROI (%)")
    axes[0].set_title("Avg Return on Investment by Strategy")
    axes[0].grid(alpha=0.3, axis="x")

    by_cohort = user_perf_df.groupby("cohort")["roi_pct"]
    cohorts = list(by_cohort.groups.keys())
    data = [by_cohort.get_group(c).values for c in cohorts]
    axes[1].boxplot(data, labels=cohorts)
    axes[1].set_ylabel("ROI (%)")
    axes[1].set_title("ROI Distribution: Original Users vs New Entrants")
    axes[1].grid(alpha=0.3, axis="y")

    fig.tight_layout()
    return _save(fig, out_dir, "strategy_performance.png")


def plot_elo(dfs, out_dir):
    """Humans vs. permanent bots -- since both draw from the exact same
    strategy distribution (see config.py), these two lines should track
    each other closely with no systematic gap; a persistent gap would flag
    a real behavioral asymmetry between the two populations."""
    df = dfs["elo"]
    fig, ax = plt.subplots(figsize=(9, 5))

    ax.plot(df["tournament"], df["avg_human_elo"], color="#2563eb", label="Avg human ELO")
    ax.fill_between(df["tournament"], df["min_human_elo"], df["max_human_elo"],
                    color="#93c5fd", alpha=0.3, label="Human min-max range")
    ax.plot(df["tournament"], df["avg_bot_elo"], color="#dc2626", linestyle="--", label="Avg bot ELO")
    ax.set_xlabel("Tournament #")
    ax.set_ylabel("ELO")
    ax.set_title("Investing-Skill ELO Over Time (humans vs. permanent bots)")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    fig.tight_layout()
    return _save(fig, out_dir, "elo_over_time.png")


def plot_cash_ratio_and_inequality(dfs, out_dir):
    econ = dfs["economy"]
    users = dfs["users"]
    fig, axes = plt.subplots(1, 2, figsize=(11, 5))

    axes[0].plot(econ["tournament"], econ["cash_ratio"] * 100, color="#0891b2")
    axes[0].axhspan(15, 30, color="#22c55e", alpha=0.15, label="Spec healthy range (15-30%)")
    axes[0].set_xlabel("Tournament #")
    axes[0].set_ylabel("Cash ratio (%)")
    axes[0].set_title("Cash Ratio Over Time")
    axes[0].legend(fontsize=8)
    axes[0].grid(alpha=0.3)

    axes[1].plot(users["tournament"], users["gini_net_worth_all"], color="#7c3aed", label="All users")
    axes[1].plot(users["tournament"], users["gini_net_worth_humans"], color="#f59e0b", label="Humans only")
    axes[1].set_xlabel("Tournament #")
    axes[1].set_ylabel("Gini coefficient")
    axes[1].set_title("Wealth Inequality Over Time")
    axes[1].legend(fontsize=8)
    axes[1].grid(alpha=0.3)

    fig.tight_layout()
    return _save(fig, out_dir, "cash_ratio_and_inequality.png")


def generate_all_charts(dfs, players, out_dir, user_perf_df=None):
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    paths.append(plot_market_cap_over_time(dfs, out_dir))
    paths.append(plot_share_prices_over_time(dfs, players, out_dir))
    paths.append(plot_user_wealth_distribution(dfs, out_dir))
    paths.append(plot_dividend_generation(dfs, out_dir))
    paths.append(plot_trading_volume(dfs, out_dir))
    paths.append(plot_ownership_concentration(dfs, out_dir))
    paths.append(plot_liquidity_health(dfs, out_dir))
    paths.append(plot_cash_ratio_and_inequality(dfs, out_dir))
    if "elo" in dfs and len(dfs["elo"]) > 0:
        paths.append(plot_elo(dfs, out_dir))
    if user_perf_df is not None and len(user_perf_df) > 0:
        paths.append(plot_strategy_performance(user_perf_df, out_dir))
    return paths
