# Changes from v3 -> v4 (this delivery)

Implements the "Forecast -- Complete Economy, Market, and Simulation
Design Specification" (the ChatGPT-planning-doc spec) on top of the
working v3 simulator. v3's own features (dynamics.py sentiment/rumors,
entrants.py new users, 12 human trading strategies, liquidity
experiments) are all still present and unchanged in kind -- nothing was
removed, only extended. See README.md's new "v2 spec implementation"
section for the full design-decision writeup; this file is the flat
list of exactly what changed, file by file.

## New files

- `forecast_sim/elo.py` -- ELO investing-skill rating + seasonal points.
- `forecast_sim/success_criteria.py` -- pass/fail evaluation against the
  spec's "Success Metrics" thresholds.
- `forecast_sim/report.py` -- `summary_report.txt` builder, split out of
  `main.py` so `experiments.py` can reuse the same success-criteria pipeline.
- `experiments.py` -- parameter sweep across every axis in the spec's
  "Experiments to Run" section (supersedes nothing; `liquidity_experiment.py`
  is still here and still works).

## Modified files

- `forecast_sim/config.py` -- new population fields (`num_initial_humans`,
  `num_bots`, `human_entrant_growth_target` replacing the old flat
  `num_users`/open-ended entrant growth); `DIVIDEND_POOL_TIERS` +
  `dividend_pool_tier` (replaces the flat `tournament_prize_pool`);
  `cash_cup_count`/`fncs_count`/`global_count` (replaces flat
  `num_tournaments`, now a derived property); `transaction_fee_rate`;
  `min_share_price`; `auction_entry_fee_fraction` default 0.0 -> 0.01;
  `bot_strategy_weights`; `news_events_per_tournament_min/max` +
  `news_type_weights` + per-event-type impact knobs; `mm_*` liquidity-
  provider knobs; `elo_*` / `seasonal_points_per_win_pctile`; grid
  constants (`TRANSACTION_FEE_GRID` etc.) for `experiments.py`.
- `forecast_sim/models.py` -- `Player`: `is_rookie`, `retired_tournament`,
  `recent_news_score`. `User`: `is_bot`, `elo`, `elo_history`,
  `prev_snapshot_net_worth`, `seasonal_points`, `mm_players`.
- `forecast_sim/population.py` -- `generate_users()` now builds humans +
  permanent bots separately (bots get the fixed 5-category strategy mix,
  liquidity-provider bots get a fixed set of market-making players
  assigned once); new `make_rookie_player()` for the retirement news event.
- `forecast_sim/auction.py` -- minimum share price floor; auction fee
  changed from "extra cost, never tracked" to "extra cost, tracked in
  `Market.auction_fees_removed`" (proportionally trimmed if it would push
  a bidder over their cash, instead of just capping and dropping the fee
  silently).
- `forecast_sim/market.py` -- transaction fee added at all 6 trade-
  execution sites (limit-order crossing x2, Quick Buy, Quick Sell),
  "taker pays" model: the side whose order executes immediately pays the
  fee, the resting/maker side is unaffected. Resting buy-order escrow now
  reserves `price * (1 + fee)`, not just `price` (and refunds correctly).
  `total_escrowed_buy_cash()` / `escrowed_cash_by_user()` /
  `expire_stale_orders()` all updated to account for the fee portion of
  escrow so per-user net worth stays exactly right.
- `forecast_sim/tournament.py` -- `build_event_schedule()` (new): 36 Cash
  Cup + 3 FNCS + 1 Global event schedule with per-tier prize pools.
  `compute_payouts()` now takes `prize_pool` as a parameter instead of
  reading a single flat config value.
- `forecast_sim/dynamics.py` -- rumor-starting moved out of the
  independent per-player-per-tournament roll and into
  `generate_news_events()` as one event type among six (retirement, duo
  change, new teammate, performance slump, meta change, roster rumor);
  `recent_news_score` decay added to `pre_tournament_update()`.
- `forecast_sim/entrants.py` -- bots removed entirely from this path
  (humans only); replaced the old open-ended
  `new_entrant_prob_per_round` + `max_total_users` cap with
  `join_pacing()`, calibrated to a specific growth target
  (`human_entrant_growth_target`) instead of an unbounded rate.
- `forecast_sim/strategies.py` -- `MarketSnapshot` gained
  `recent_dividend_per_share` / `dividend_yield()`; new buy/sell branches
  for `value_investor` and `news_trader`; `STRATEGY_PROFILE` entries for
  both plus `liquidity_provider` (profile exists for completeness --
  liquidity_provider never actually goes through the generic dispatch).
- `forecast_sim/trading.py` -- `_run_market_maker()` (new): dedicated
  two-sided-quoting routine for `liquidity_provider` bots, bypassing the
  normal buy-or-sell dispatch entirely.
- `forecast_sim/metrics.py` -- `gini()` / `top_share()` helpers;
  `cash_ratio`, per-fee-sink cumulative totals, human/bot split, Gini
  (all + humans-only), top-10%/1% wealth share added to the existing
  economy/user rows; new `elo` dataframe (avg/median/min/max human ELO,
  avg bot ELO, avg human seasonal points per tournament).
- `forecast_sim/simulator.py` -- wires the event schedule, news
  generation, ELO/seasonal update, and paced entrant growth into the main
  loop; tracks `news_log`, `retirement_count`, `used_player_names` (for
  rookie name generation).
- `forecast_sim/visualize.py` -- two new charts: `cash_ratio_and_inequality.png`,
  `elo_seasonal_points.png`.
- `main.py` -- new CLI flags (`--dividend-tier`, `--transaction-fee`,
  `--bank-spread`, `--humans`, `--bots`, `--human-growth`); `--tournaments`
  now adjusts `cash_cup_count` instead of a flat field;
  `user_performance.csv` gained `is_bot`, `elo`, `seasonal_points`,
  `trade_count`, `trade_notional`, `turnover_x_starting_cash`,
  `is_passive_holder`; report-building moved to `forecast_sim/report.py`.
- `liquidity_experiment.py` -- fixed to use the new config shape
  (`num_initial_humans + num_bots` instead of the removed `num_users`,
  `dividend_pool_override` instead of the removed `tournament_prize_pool`,
  `human_entrant_growth_target` instead of the removed
  `new_entrant_prob_per_round`) -- this script would not have run
  against the new config without these fixes.

## One bug fixed along the way

`entrants.per_round_join_probability()`'s original design capped the
per-round join probability at 1.0 with a fixed 1-2 batch size, which
silently under-delivered any growth target bigger than
`total_rounds * ~1.5` (e.g. requesting +400 humans over a 40-event/
120-round season could only ever produce ~180). Replaced with
`join_pacing()`, which scales the batch size up once probability would
need to exceed 1.0, so large growth targets are approximated much more
closely (see `experiments.py`'s `new_user_growth` sweep, which exercises
exactly this).

## Verification performed

- `python main.py --quick` and `python main.py` (full spec scale, 500
  participants / 40 events, ~10s) both run clean.
- `python liquidity_experiment.py` (6 full-scale scenarios, ~40s) runs
  clean against the new config.
- `python experiments.py` (38 runs at reduced scale, ~30s) runs clean.
- Money-supply reconciliation checked by hand against
  `post_auction_total_cash + dividends - fees + bank_net + entrant_cash`:
  matched the simulator's own reported total money supply to within
  0.004% (floating point / integer-share-quantity rounding noise, not a
  systematic leak).
- All 8 charts inspected visually; `cash_ratio_and_inequality.png` and
  `elo_seasonal_points.png` (the two new ones) render correctly.

---

# Changes from v4 -> v5 (this delivery)

Two rounds of changes, both driven by user feedback on v4.

## Round 1: bots must behave exactly like humans

**The problem**: v4 gave the permanent 300-bot population its own fixed
5-archetype strategy mix (per the raw spec's "Bot Types" section: 25%
Value Investor / 25% Momentum / 17% Contrarian / 17% News / 16%
Liquidity Provider), distinct from the richer 12-strategy human roster.
This made bots systematically out-earn humans on average -- average bot
ELO drifted up while average human ELO drifted down over a season. The
user correctly pointed out this defeats the purpose: bots exist so the
market isn't thin, not to be a smarter/different population.

**The fix**:
- `forecast_sim/config.py` -- deleted `bot_strategy_weights` entirely.
  `trading_strategy_weights` is now ONE shared distribution (15
  strategies: the original 12 plus `value_investor`/`news_trader`/
  `liquidity_provider`, which are now available to humans too) used
  identically for humans and bots.
- `forecast_sim/population.py` -- bots draw their trading strategy AND
  their auction-day strategy from the exact same weighted random draw a
  human gets. Removed the old deterministic trading-strategy ->
  auction-strategy mapping that only applied to bots.
- `experiments.py` -- `sweep_bot_mix`/`BOT_MIX_GRID` renamed to
  `sweep_strategy_mix`/`STRATEGY_MIX_GRID`; the mix now applies to the
  whole population, not just bots.
- `is_bot` remains purely a bookkeeping flag (lets reporting separate
  "the fixed 300-bot depth layer" from "the growing human population") --
  it no longer changes any decision a user makes.

**Verified**: a 3-seed spot check showed the ELO gap between original-
cohort humans and bots dropped from a systematic ~-250 (bots winning) to
a few points either direction (noise) -- confirmed at scale by the
100-run batch below.

## Round 2: locked-in economic parameters + a real bug found along the way

The user specified exact final parameters:
- Removed seasonal points entirely -- `User.seasonal_points`, the
  seasonal-points half of `elo.py` (renamed `update_elo_and_seasonal_points`
  -> `update_elo`), the seasonal-points column/chart/report lines are all
  gone. The system is investing + dividends (+ELO as the skill metric) only.
- Auction fee changed from a 1%-of-spend proportional fee to a **flat
  $10,000** charged once per participant (human or bot) before their
  auction budget is computed (`auction_entry_fee_flat`, `auction.py`).
- Cash treasury yield **enabled** (was an unused 0.0 knob): 0.02% per
  event on every user's LIQUID cash (not cash tied up in open orders),
  credited as new money exactly like a dividend
  (`apply_treasury_yield()` in `tournament.py`, wired into
  `simulator.py` right after each event's dividends). ~0.8% realized
  over the 40-event season (36 Cash Cup + 3 FNCS + 1 Global).
- New human entrants **disabled by default** (`enable_new_entrants =
  False`) -- population is fixed at 350 (50 humans + 300 bots) for the
  whole chapter. The mechanism is untouched and still works if re-enabled.
- Dividend pools were already exactly right (baseline tier: 36x$300k +
  3x$1.5M + 1x$3M = $18.3M, ~5.23% of the $350M starting economy) and
  the 0.25% transaction fee was already the default -- no change needed
  to either.

**Bug found while verifying the $18.3M dividend total**: the initial
auction's per-user share rounding (`int(round((bid/tb) * shares_issued))`,
independently for every bidder) doesn't guarantee the shares actually
allocated across all bidders sum to `shares_issued` -- with hundreds of
bidders per player, this was silently OVER-issuing shares (found 96/200
players with more shares in circulation than they were supposed to have,
right after the auction, before any trading). More circulating shares
means more dividends paid out than the nominal prize pool, which is
exactly the ~$35k/season discrepancy that showed up while checking the
dividend total against the user's $18.3M figure. Fixed by replacing
independent rounding with an exact largest-remainder (Hamilton)
apportionment in `auction.py`: every bidder's exact fractional
entitlement is floored, then the handful of leftover shares go one at a
time to the largest fractional remainders, guaranteeing the allocated
total is exactly `shares_issued`, always. Verified via a full
share-conservation check (0 mismatches across all 200 players, both
immediately post-auction and at the end of a full run) and the dividend
total now lands within 0.1% of the exact $18.3M nominal figure (the
residual gap is the Bank's tiny, intentional, un-credited share of a
few dividends -- see `report.py`'s inflation section).

## 100-run validation batch (`symmetry_batch.py` + `analyze_symmetry.py`)

Per the user's request for a decent sample size: 100 full-scale runs (200
players, 40 events, the exact locked-in economics above) across 5
population-wide strategy-mix presets x 4 bot:human ratios (100/200/300/500
bots, humans fixed at 50) x 5 seeds, comparing original-cohort humans to
bots directly (same tenure, same strategy-draw distribution, so any
nonzero gap should be pure sampling noise post-fix).

**Result: the fix holds up.** Pooled across all 100 runs, the mean
ELO gap (orig human - bot) is -3.14 (SE 2.03, p=0.12 -- not
significant). Every strategy-mix subgroup and every bot-ratio subgroup's
95% CI comfortably includes zero. Of the 20 individual mix x ratio cells
(n=5 seeds each, low power), exactly 1 flags at |z|>2 -- almost exactly
what you'd expect from chance alone with 20 cells at a ~5% false-positive
rate. See `symmetry_analysis/symmetry_analysis_summary.txt` for the full
numeric breakdown and `elo_gap_by_axis.png` / `elo_gap_heatmap.png` /
`z_score_distribution.png` for the visuals.

**Where the economy DOES show real, non-noise sensitivity** (this is
about overall health, not the bot/human symmetry question): fewer bots
means a measurably worse economy -- `bot_light_100bots` averages 83.9%
inflation and only 2.8/7 success-criteria passes across the grid, versus
`bot_heavy_500bots` at 23.7% inflation and 3.8/7 passes. The spec's own
300-bot default sits in between (36.2% inflation, 3.5/7). Strategy-mix
concentration also matters some -- the balanced `default` mix
outperforms every single-flavor alternative (momentum_heavy,
fundamentals_heavy, chaos_heavy, liquidity_heavy) on success-criteria
pass rate. Neither of these is a symmetry problem; they're genuine
"how much bot liquidity/how homogeneous a strategy mix does this economy
need" findings, exactly the kind of thing this simulator exists to surface.
