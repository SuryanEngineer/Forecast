"""
Evaluates a completed run against the spec's "Success Metrics" section:

    Cash ratio:      15-30%
    Trading:         high activity, large % of assets exchanged
    Inflation:       moderate, not explosive
    Dividends:       20-40% of investor returns
    New users:       can still become competitive
    Market:          no permanently dead assets
    Bots:            maintain liquidity

The spec gives exact numbers for cash ratio and dividend share but leaves
the rest qualitative ("high activity", "moderate", "no permanently dead
assets", "maintain liquidity"). Where a hard number was needed to turn
those into a pass/fail check, the threshold and the reasoning behind it
is documented inline in the corresponding _check_* function -- treat
those as *this simulator's* operationalization of the spec's intent, not
a value handed down by the spec itself.
"""

import numpy as np


class Criterion:
    def __init__(self, name, verdict, measured, detail):
        self.name = name
        self.verdict = verdict   # "PASS" | "MARGINAL" | "FAIL"
        self.measured = measured
        self.detail = detail

    def line(self):
        return f"[{self.verdict:8s}] {self.name}: {self.measured}\n            {self.detail}"


def _verdict_range(value, lo, hi, margin):
    if lo <= value <= hi:
        return "PASS"
    if lo - margin <= value <= hi + margin:
        return "MARGINAL"
    return "FAIL"


def check_cash_ratio(dfs) -> Criterion:
    econ = dfs["economy"]
    tail = econ["cash_ratio"].iloc[-max(1, len(econ) // 4):]
    avg = float(tail.mean())
    verdict = _verdict_range(avg * 100, 15, 30, 5)
    return Criterion(
        "Cash ratio (spec target: 15-30%)", verdict, f"{avg*100:.1f}%",
        "Cash's share of total investor net worth (cash + escrow + equity), "
        "averaged over the last quarter of the run. Too low = everyone's "
        "fully invested with no dry powder for opportunities; too high = "
        "capital is sitting idle instead of pricing players.",
    )


def check_trading_activity(dfs) -> Criterion:
    mkt = dfs["market"]
    n = len(mkt)
    first_q = mkt["trading_volume_pct_of_market_cap"].iloc[: max(1, n // 4)].mean()
    last_q = mkt["trading_volume_pct_of_market_cap"].iloc[-max(1, n // 4):].mean()
    # Operationalization: "high activity, large % of assets exchanged" ->
    # at least ~1% of total market cap turning over per event, and not
    # collapsing to less than half of its early-run level.
    level_ok = last_q >= 0.01
    trend_ok = last_q >= 0.5 * first_q
    if level_ok and trend_ok:
        verdict = "PASS"
    elif level_ok or trend_ok:
        verdict = "MARGINAL"
    else:
        verdict = "FAIL"
    return Criterion(
        "Trading activity (spec: high, large % of assets exchanged)", verdict,
        f"{last_q*100:.2f}% of market cap/event (last quarter) vs {first_q*100:.2f}% (first quarter)",
        "Threshold (>=1% of market cap turning over per event, not decaying "
        "below half its early-run level) is this simulator's reading of "
        "'high activity' -- the spec doesn't give an exact number.",
    )


def check_inflation(sim, dfs) -> Criterion:
    econ = dfs["economy"]
    start_cash = sim.post_auction_total_cash
    end_cash = econ["total_money_supply"].iloc[-1]
    pct = (end_cash - start_cash) / start_cash * 100 if start_cash else 0.0
    # Operationalization of "moderate, not explosive": growth roughly in
    # line with (not wildly exceeding) cumulative dividends injected as a
    # fraction of the starting economy.
    if 0 <= pct <= 300:
        verdict = "PASS"
    elif -20 <= pct < 0 or 300 < pct <= 600:
        verdict = "MARGINAL"
    else:
        verdict = "FAIL"
    return Criterion(
        "Inflation (spec: moderate, not explosive)", verdict, f"{pct:+.1f}% over the run",
        "Total money supply growth from the post-auction baseline. Bands "
        "(0-300% moderate, up to 600% marginal, beyond that or net "
        "deflation flagged) are this simulator's threshold, not the spec's.",
    )


def check_dividend_share_of_return(sim, dfs) -> Criterion:
    econ = dfs["economy"]
    total_dividends = econ["dividends_paid_this_round"].sum()
    prices_df = dfs["price_history"]
    first_t, last_t = prices_df["tournament"].min(), prices_df["tournament"].max()
    p0 = prices_df[prices_df["tournament"] == first_t].set_index("player_id")["price"]
    p1 = prices_df[prices_df["tournament"] == last_t].set_index("player_id")["price"]
    common = sorted(set(p0.index) & set(p1.index))
    shares = {pid: sim.players_by_id[pid].shares_issued for pid in common if pid in sim.players_by_id}
    appreciation = sum((p1[pid] - p0[pid]) * shares.get(pid, 0) for pid in common)
    appreciation = max(0.0, appreciation)  # a market-wide decline isn't a "return" to split
    denom = total_dividends + appreciation
    share = total_dividends / denom * 100 if denom > 0 else 0.0
    verdict = _verdict_range(share, 20, 40, 10)
    return Criterion(
        "Dividends as % of total investor return (spec target: 20-40%)", verdict,
        f"{share:.1f}%",
        f"Total dividends paid (${total_dividends:,.0f}) vs. total player-level "
        f"capital appreciation (${appreciation:,.0f}). If this is too low, price "
        f"speculation is drowning out the intrinsic-value anchor the spec "
        f"relies on; too high and there's no capital-gains upside to investing well.",
    )


def check_new_user_competitiveness(user_perf_df) -> Criterion:
    if user_perf_df is None or len(user_perf_df) == 0:
        return Criterion("New users can still compete", "FAIL", "n/a", "No user performance data.")
    entrants = user_perf_df[(user_perf_df["cohort"] == "new_entrant") & (~user_perf_df.get("is_bot", False))]
    originals = user_perf_df[(user_perf_df["cohort"] == "original") & (~user_perf_df.get("is_bot", False))]
    # Only entrants who've had a meaningful amount of time in the market --
    # someone who joined last week can't be expected to have caught up yet.
    seasoned_entrants = entrants[entrants["tournaments_active"] >= entrants["tournaments_active"].max() * 0.5] \
        if len(entrants) else entrants
    if len(seasoned_entrants) == 0 or len(originals) == 0:
        return Criterion("New users can still compete", "MARGINAL", "insufficient data",
                          "Not enough seasoned entrants or original-cohort humans to compare.")
    orig_roi = originals["roi_pct"].mean()
    ent_roi = seasoned_entrants["roi_pct"].mean()
    ratio = ent_roi / orig_roi if orig_roi not in (0, None) and orig_roi > 0 else (1.0 if ent_roi >= 0 else 0.0)
    if ent_roi >= 0 and ratio >= 0.5:
        verdict = "PASS"
    elif ent_roi >= 0 or ratio >= 0.25:
        verdict = "MARGINAL"
    else:
        verdict = "FAIL"
    return Criterion(
        "New users can still become competitive", verdict,
        f"seasoned entrants avg ROI {ent_roi:+.1f}% vs original cohort {orig_roi:+.1f}%",
        "'Seasoned' = active for at least half the longest entrant tenure. "
        "PASS requires entrants' ROI be non-negative and at least half the "
        "original cohort's -- a threshold chosen for this check, not stated "
        "verbatim in the spec.",
    )


def check_no_dead_assets(sim, dfs) -> Criterion:
    trade_counts = {p.player_id: 0 for p in sim.players}
    for t in sim.market.trade_log:
        trade_counts[t.player_id] = trade_counts.get(t.player_id, 0) + 1
    dead = [pid for pid, c in trade_counts.items() if c == 0]
    n_dead = len(dead)
    verdict = "PASS" if n_dead == 0 else ("MARGINAL" if n_dead <= max(1, len(sim.players) * 0.02) else "FAIL")
    return Criterion(
        "No permanently dead assets", verdict, f"{n_dead}/{len(sim.players)} players never traded once",
        "A 'dead' asset here means zero trades of any kind (Quick Buy/Sell "
        "or limit fill) across the entire run.",
    )


def check_bot_liquidity(dfs) -> Criterion:
    mkt = dfs["market"]
    econ = dfs["economy"]
    tail_n = max(1, len(mkt) // 4)
    bank_share_tail = econ["bank_share_pct_of_supply"].iloc[-tail_n:].mean()
    avg_depth_tail = mkt["avg_order_book_depth"].iloc[-tail_n:].mean()
    # Operationalization: liquidity is healthy if the Bank hasn't ended up
    # owning most of the float (which would mean nobody -- including the
    # permanent bot population -- is providing real two-sided liquidity
    # anymore, just draining to the Bank) and resting order-book depth
    # hasn't collapsed to near zero.
    bank_ok = bank_share_tail <= 0.5
    depth_ok = avg_depth_tail >= 1.0
    verdict = "PASS" if (bank_ok and depth_ok) else ("MARGINAL" if bank_share_tail <= 0.7 else "FAIL")
    return Criterion(
        "Bots maintain liquidity", verdict,
        f"Bank holds {bank_share_tail*100:.1f}% of total share supply, "
        f"avg order-book depth {avg_depth_tail:.1f} resting orders/player (last quarter avg)",
        "If the Bank ends up holding most of the float, or resting orders "
        "dry up, real participants (including the permanent bot "
        "population) have stopped providing two-sided liquidity.",
    )


def evaluate_run(sim, dfs, user_perf_df):
    checks = [
        check_cash_ratio(dfs),
        check_trading_activity(dfs),
        check_inflation(sim, dfs),
        check_dividend_share_of_return(sim, dfs),
        check_new_user_competitiveness(user_perf_df),
        check_no_dead_assets(sim, dfs),
        check_bot_liquidity(dfs),
    ]
    return checks


def format_report(checks) -> str:
    lines = ["SUCCESS CRITERIA (spec 'Success Metrics' section)", "-" * 55]
    n_pass = sum(1 for c in checks if c.verdict == "PASS")
    for c in checks:
        lines.append(c.line())
        lines.append("")
    lines.append(f"{n_pass}/{len(checks)} criteria fully PASS.")
    return "\n".join(lines)
