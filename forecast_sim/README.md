# Forecast Economy Simulator

A modular Python simulator for testing the economics of **Forecast**, a
Fortnite-esports stock market where users buy ownership stakes in
competitive players and earn dividends from tournament winnings.

This is now a full implementation of the "Forecast -- Complete Economy,
Market, and Simulation Design Specification" (v2): a permanent 300-bot
population alongside a growing human population (50 -> 200), tiered
tournaments (36 Cash Cups / 3 FNCS / 1 Global Championship per chapter)
with three dividend-pool scenarios, a transaction fee + auction fee as
inflation controls, an ELO investing-skill rating with seasonal points,
and expanded simulated news (retirements, duo changes, meta shifts, on
top of the existing team-switch-rumor/sentiment-overreaction system). See
**"v2 spec implementation" below** for the full spec-section -> code
mapping and how it layers on top of everything documented further down in
this file (which still describes the original Alpha-spec mechanics
accurately -- auction, Bank, order book, dividends, strategies, dynamics,
new entrants, liquidity -- all of that is unchanged in kind, only
extended).

## Quick start

```bash
pip install numpy pandas matplotlib
python main.py                 # full spec-scale run: 200 players, 50->200 humans, 300 bots, 40 events
python main.py --quick         # fast smoke test: 40 players, 10->25 humans, 30 bots, 13 events
python main.py --tournaments 50 --seed 7
python main.py --payout-curve power
python main.py --dividend-tier aggressive --transaction-fee 0.005 --bank-spread 0.05
python experiments.py          # parameter sweep across every axis in the spec's "Experiments to Run"
python liquidity_experiment.py # the original auction-drain / liquidity-stall stress test
```

Each run creates a timestamped folder under `output/`, e.g.
`output/run_20260101_120000/`, containing:

| File | Contents |
|---|---|
| `economy_metrics.csv` | money supply, market cap, dividends per tournament |
| `market_metrics.csv` | trading volume, bid/ask spread, order book depth |
| `ownership_metrics.csv` | largest-owner %, HHI concentration, active holders |
| `users_metrics.csv` | net worth distribution, top/bottom users |
| `players_metrics.csv` | highest/lowest valued players, biggest gainers/losers |
| `price_history_metrics.csv` | every player's price at every tournament (long-form) |
| `auction_summary.csv` | initial per-player auction results |
| `summary_report.txt` | plain-English answers to the spec's 9 "Goals of Simulation" questions |
| `*.png` | the 6 requested charts |

## Project layout

```
forecast_sim/
  config.py            SimConfig dataclass -- every tunable knob in one place
  models.py             Player, User, Order, Trade data structures
  population.py         generates players + the initial 50 humans / 300 bots
  auction.py             initial auction: cash -> shares at t=0 (min price + auction fee)
  market.py             order books, Bank, Quick Buy/Sell, limit-order matching, transaction fee
  strategies.py         auction bot archetypes + trading bot archetypes (human + permanent-bot)
  tournament.py         event schedule (Cash Cup/FNCS/Global), placements, payouts, dividends
  trading.py            one round of bot trading activity + liquidity-provider market making
  dynamics.py           skill drift/form/sentiment + simulated news events (incl. retirement)
  entrants.py           paced human population growth (bots are fixed/permanent)
  elo.py                 ELO investing-skill rating + seasonal points
  metrics.py            collects economy/market/ownership/user/player/ELO metrics
  success_criteria.py   evaluates a run against the spec's "Success Metrics" thresholds
  report.py              builds summary_report.txt (narrative + success criteria)
  simulator.py          orchestrates: setup -> [news -> tournament -> dividends -> trading -> ELO -> snapshot]*
  visualize.py          generates all charts from the metrics
main.py                 CLI entry point, writes CSVs/charts/summary report
experiments.py          parameter sweep across every axis in the spec's "Experiments to Run"
liquidity_experiment.py  the original auction-drain / liquidity-stall stress test (6 scenarios)
```

Everything is driven off `SimConfig` (`forecast_sim/config.py`) -- to run an
experiment, either edit the defaults there, pass CLI flags, or construct a
`SimConfig(...)` directly and call `Simulator(cfg).setup()` / `.run()` from
a notebook/script.

## Design decisions & assumptions

The spec is intentionally a loose "alpha" design doc; several mechanics
needed a concrete rule to actually simulate. Every non-obvious choice is
commented at the point it's made in the code. The main ones:

- **Skill distribution**: `base + Pareto tail`, clipped to `[1, 100]`, so a
  small number of players are elite (Peterbot/Pollo-tier) and most cluster
  near the base/average level.
- **Initial auction**: each user's bot strategy produces a weight vector
  over all 200 players; 85% of starting cash is committed as bids. A
  player's initial price is `total_bids / shares_issued`; shares split
  proportionally to each user's share of total bids. A player who receives
  *zero* bids leaves all 5,000 shares with the Bank at a baseline price
  (there's no way to proportionally split zero).
- **Bank pricing**: Quick Buy price = highest active bid × 1.10 (falls back
  to last trade price, then baseline, if the book is empty). Quick Sell
  price (Bank buying from a user) = lowest active ask × 0.90, using the
  same fallback chain -- the spec only fully specifies the Quick Buy side.
- **Order escrow**: limit orders escrow cash/shares immediately at
  placement and refund any unused portion once filled, so a user can never
  spend or sell more than they actually have. This means `total cash`
  understates users' money if you don't also count cash tied up in open
  buy orders -- see `total_escrowed_buy_cash` / `total_money_supply` in
  `economy_metrics.csv`, which is the reconciling "total money in the
  economy" figure (dividends injected ≈ money supply growth).
- **Tournament placements**: `performance_score = skill_rating +
  Normal(0, volatility_rating × noise_scale)`, ranked descending. Higher
  skill wins more often; high-volatility players create regular upsets.
- **Payout curve**: configurable exponential decay (`decay^(rank-1)`) or
  power law (`rank^-power`) over the top `payout_placements` finishers,
  scaled to sum to the tournament's prize pool.
- **Dividends**: `payout / shares_issued` per share, paid to every
  shareholder in proportion to holdings. This is new money (not
  transferred from anyone) -- it's the simulator's inflation engine.
  Bank-held shares generate a dividend amount that isn't credited to any
  cash balance, consistent with Bank cash being explicitly untracked /
  an infinite sink in the spec.
- **Trading bots**: 40% of users act in each of 3 trading rounds per
  tournament. Each acting bot either buys (per its strategy's target-
  picking rule) or -- if it holds any shares -- has a 45% chance to instead
  sell a position, so portfolios don't only ever grow. Roughly half of
  trade actions are Quick Buy/Sell, half are resting limit orders (adds
  order-book depth); tunable via `limit_order_probability`.
- **Strategy interpretation** (spec gives one-line descriptions, mapped to
  concrete signals):
  - `dividend_hunter` -- buys players with the best recent tournament
    placement (proxy for dividend strength).
  - `speculator` -- buys players whose most recent placement beat their
    historical average (an improving trend not yet priced in).
  - `momentum_trader` -- buys recent price gainers, sells recent losers.
  - `contrarian` -- buys recent price decliners, takes profit on gainers.
  - `index_investor` -- buys whatever it holds least of; trims whatever
    position has grown largest (stays diversified).
  - `value_investor` (auction-only) -- favors mid/high skill players while
    discounting the very top tier, on the theory the top tier gets bid up
    by star_chasers.
  - `star_chaser` (auction-only) -- weight ∝ skill³, heavily top-heavy.
  - `random` -- self-explanatory.

## Known alpha-parameter finding

With the spec's example defaults (`$500,000` prize pool × 100 tournaments
against a `$50,000,000` starting cash pool), the simulator shows **severe
inflation**: total dividends paid over a full run (~$50M) are comparable
to the entire starting capital base, and total money supply grows several
hundred percent over the run (see `summary_report.txt`, question 1, and
`market_cap_over_time.png`). That's the kind of result this simulator
exists to surface -- `tournament_prize_pool` and `num_tournaments` are the
two easiest levers to bring inflation back under control if that's not the
intended design.

## New entrants (users joining mid-season)

`enable_new_entrants=True` by default. Each trading round there's a
`new_entrant_prob_per_round` chance that 1-2 new users join with a fresh
`new_entrant_cash` balance ("the starting income," same $1M as the
original cohort), occasionally at `new_entrant_whale_cash_multiplier`x
size (a rare "whale enters" event). A new entrant immediately deploys
`new_entrant_spend_fraction` of that cash across several positions using
its own assigned strategy's normal buy-target logic -- reused directly
from `strategies.py`, so a new `smart_money` entrant looks for undervalued
players on day one, a new `hype_chaser` buys hype, etc.

Every user carries `joined_tournament` and `starting_cash_at_join`, so
`user_performance.csv` (and `strategy_performance.png`) report ROI split
by **original cohort vs. new entrants** -- how late joiners actually do
relative to day-one holders.

### Does draining cash in the auction stall the market?

This was a real concern worth testing directly: the initial auction has
no seller (shares are newly issued), so `auction_spend_fraction` of every
user's cash effectively leaves circulation to capitalize the players. If
that fraction is high, very little cash is left for post-auction trading.
Two safeguards exist for this:

- `auction_spend_cap_fraction` -- a hard additional cap (independent of
  each strategy's own bidding appetite) on what fraction of starting cash
  the auction can ever consume. Set below 1.0 to force more dry powder to
  survive the auction.
- New entrants (above) act as an ongoing liquidity top-up throughout the
  season, not just a one-time fix.

`liquidity_experiment.py` stress-tests this directly with six scenarios
(auction spend from 25% to 99% of cash, prize pools from $50k to $500k,
entrants on/off, entrant size normal vs. large) -- see
`liquidity_experiment/liquidity_experiment_summary.txt` and
`liquidity_experiment_comparison.png` for the results. Two findings stood
out:

1. **The market is more resilient to a cash-starved auction than expected,
   on its own.** Trade sizing is percentage-of-current-cash (not a fixed
   dollar amount) and half of trading actions are sells (which need
   shares, not cash, and everyone has shares from the auction), so volume
   decays gracefully rather than collapsing to zero even when 99% of cash
   was spent at auction and the dividend pool is cut 10x. Nobody's cash
   balance is a hard floor at zero the way a fixed trade size would cause.
2. **New entrants still matter substantially.** Across every scenario
   tested, enabling entrants roughly doubled late-run trading volume,
   pulled the Bank's share of total supply down (fresh buyers absorb Bank
   inventory that would otherwise just sit there), and of course grew the
   participant base 2-4x by the end of the run. If you want a visibly
   "restarted" market after a cash crunch rather than just a slow bleed,
   entrants are the more effective lever -- lowering
   `auction_spend_cap_fraction` mainly prevents the crunch from being as
   deep in the first place.

Run it yourself: `python3 liquidity_experiment.py`.

## Expanded strategy roster

12 ongoing trading archetypes now exist (`strategies.py`), covering the
originally-specified ones plus several modeling real competitive-scene
psychology:

- `dividend_hunter`, `speculator`, `momentum_trader`, `contrarian`,
  `index_investor`, `random` -- as before.
- `panic_seller` -- dumps a holding hard on ANY single bad recent result,
  wildly disproportionate to the actual price move (the "one bad game and
  they're gone" community reaction).
- `hype_chaser` -- FOMOs into whatever's currently most over-hyped
  relative to true skill (`sentiment - skill_rating`), including rumored
  team upgrades; rotates out as the hype cools.
- `smart_money` -- the "some people realize it was overblown" strategy:
  explicitly trades the gap between true skill and community sentiment,
  buying panic-sold dips and taking profit on overhyped positions.
- `rumor_trader` -- trades team-switch rumors directly: buys players
  rumored to be joining a stronger lineup, exits ones rumored to be
  leaving/downgrading.
- `team_loyalist` -- rarely trades at all (70% chance to skip any round
  it's chosen), effectively never sells, holds through drama.
- `scalper` -- frequent, small, fast in-and-out trades on whatever's
  moving, in either direction.
- `whale` -- large capital, large position sizes (3.5x normal), concentrated
  in top-skill talent; genuinely moves prices when it trades.

Per-strategy sizing/behavior (position size multiplier, chance of sitting
a round out, preference for quick vs. resting orders) lives in
`STRATEGY_PROFILE` at the bottom of `strategies.py`.

## Community sentiment, streaks, and team-switch rumors (`dynamics.py`)

Modeled per the "real Fortnite scene" request:

- **True skill drifts.** `skill_rating` does a small mean-reverting random
  walk each tournament (`skill_drift_std` / `skill_mean_reversion`) --
  players genuinely get better or worse over a season, not just noisy.
- **Form (hot streaks / slumps).** A separate AR(1) process
  (`form_persistence` / `form_noise_scale`) is added to skill for
  placement generation only -- creates real, autocorrelated streakiness
  distinct from one-off luck.
- **Sentiment overreacts, then partially corrects.** `sentiment` (what
  trading bots actually read) mean-reverts toward true skill each
  tournament, but each tournament's luck is added back in amplified by
  `overreaction_factor` (default 2.5x) -- i.e. the community overreacts to
  a single result, and only some of that overreaction unwinds before the
  next result arrives. `smart_money` explicitly exploits the gap;
  `hype_chaser` and `panic_seller` amplify it.
- **Team-switch rumors.** Each tournament, any player has a small chance
  (`rumor_start_prob_per_player`) of a rumor starting (joining a
  stronger/weaker team), which live for 2-5 tournaments, adds extra
  placement/sentiment volatility while active
  (`rumor_volatility_multiplier` / `rumor_sentiment_shock_scale`), and
  resolves as confirmed (a real, permanent skill shift) or debunked
  (`rumor_confirm_prob`, default 40%) -- `rumor_trader` trades these
  directly. Confirmed/debunked counts are reported in `summary_report.txt`.

## Order expiry (a realism/liquidity fix)

Resting limit orders now auto-cancel (`order_max_age_rounds`, default 12
rounds) if never filled, refunding the escrowed cash/shares -- like a real
trader eventually pulling a stale order rather than leaving money locked
up forever in an order nobody's going to hit. Without this, per-user net
worth could look far worse than reality for limit-order-heavy strategies
whose orders just sat unfilled; `escrowed_cash_by_user()` in `market.py`
is also used everywhere net worth/ROI is computed so open orders are never
mistaken for lost money.

## Liquidity-aware trade sizing (why whale entrants can't just buy everything)

Each player only has 5,000 shares issued, total. A large cash injection
(e.g. an `new_entrant_whale_cash_multiplier`-sized entrant, 8x normal by
default) trying to spend hundreds of thousands of dollars on one player in
a single Quick Buy will run out of Bank inventory + resting sell orders
almost immediately -- the rest of that order previously just failed
silently, leaving most of the whale's cash sitting undeployed as pure
cash for the rest of the run (this is exactly what was happening before
the fix: a whale entrant with $8M showed ~0% ROI because only ~$19k of it
ever actually got invested).

`max_liquidity_take_fraction` (default 0.6) now caps any single Quick Buy
to that fraction of a player's currently visible available supply (Bank
inventory + resting sell quantity), applied both to ordinary trading
(`trading.py`) and new-entrant onboarding (`entrants.py`). Large capital
now has to scale into a position gradually over multiple rounds -- slower,
but it can actually get invested and earn a return, and it's a realistic
"market impact" constraint (you can't buy more of a small-cap stock's
float than exists, either).

## Auction entry fee (leveling founder vs. new-entrant economics)

`auction_entry_fee_fraction` (default 0.0, opt-in) adds a friction cost on
top of every auction purchase -- e.g. at 0.05, a $10,000 auction position
actually costs the bidder $10,500, with the extra $500 leaving the economy
(same sink behavior as everything else the Bank absorbs). It doesn't
change how many shares they get, only what they pay for them.

This directly targets the "original users get founder pricing with zero
spread, new entrants pay the Bank's 10% spread" asymmetry -- raising it
narrows that specific gap. That said, based on `user_performance.csv`
across our sample runs, **the founder-pricing gap is a smaller factor
than tenure**: entrants who join early and get 75-100 tournaments of
compounding dividends average noticeably higher ROI than entrants who
join late and only get a handful, regardless of the one-time entry cost.
An auction fee is a reasonable lever to add if "fairness at entry" matters
to the design goals, but it won't close the entrant/original ROI gap by
itself -- that gap is mostly just "the dividend flywheel needs time to
spin up," which no one-time fee changes.

## Extending it

- Add a new bot archetype: add a branch to `auction_weights()` and/or
  `pick_buy_targets()`/`pick_sell_targets()` in `strategies.py`, then add
  it to the weight dicts in `SimConfig` (and optionally `STRATEGY_PROFILE`
  for custom sizing/skip behavior).
- Change payout shape: `payout_curve` / `payout_exp_decay` / `payout_power`
  in `config.py`.
- Model player retirement: `retirement_probability` is already generated
  per player (currently unused, per spec's "future use" note) -- wire it
  into `Simulator.run()` to remove/replace players between tournaments.
- Swap in a different placement model: edit `run_tournament()` in
  `tournament.py` (e.g. Plackett-Luce instead of Gaussian-noise-on-skill).
- Tune the community-psychology intensity: `overreaction_factor`,
  `rumor_start_prob_per_player`, `form_noise_scale` in `config.py`.

---

## v2 spec implementation

This section maps every part of the "Forecast -- Complete Economy,
Market, and Simulation Design Specification" (the follow-up spec) onto
the code, and documents every judgment call the same way the section
above does for the original Alpha spec.

### Population: 50 humans + 300 bots -> 200 humans + 300 bots

`SimConfig.num_initial_humans` (50) and `SimConfig.num_bots` (300) are
generated together in `population.generate_users()` and **both**
participate in the initial auction, matching the spec ("New Users do NOT
participate in auction" implies the initial cohort does). Bots are
permanent: `entrants.py` only ever creates new `User(is_bot=False, ...)`
humans, paced by `human_entrant_growth_target` (default 150) so the
population grows 50 -> 200 humans over the season while the 300 bots
never change. Every `User` now carries an `is_bot` flag used throughout
metrics/reporting to keep human and bot performance/ELO separate.

Growth pacing (`entrants.join_pacing()`) is calibrated so
`E[new humans over the season] ~= human_entrant_growth_target`, by
solving for a per-round join probability given the number of trading
rounds in the season. If the requested growth target is large enough that
even joining *every* round wouldn't hit it with the default 1-2 batch
size, the batch size scales up automatically rather than silently
under-delivering -- but very large targets relative to a short season can
still land a bit short (this is an approximation, not an exact quota).

### Bot Types (fixed 5-category distribution)

`SimConfig.bot_strategy_weights` implements the spec's percentages
exactly (Value Investors 25% / Momentum Traders 25% / Contrarians 17% /
News Traders 17% / Liquidity Providers 16%), assigned once per bot at
population generation and never reassigned. Three of these
(`momentum_trader`, `contrarian`) reuse the existing human trading
strategies directly; two are new:

- **`value_investor`** -- "buy high dividend yield." Buys whatever is
  currently paying the best $/share dividend relative to price
  (`MarketSnapshot.dividend_yield()`); falls back to skill (the best
  available proxy pre-dividend-history) early in the season. Sells its
  worst-yielding holding to rotate into better fundamentals.
- **`news_trader`** -- "react to roster events." A superset of the
  existing `rumor_trader`: reads each player's `recent_news_score`, a
  decaying signed score bumped by every duo-change/new-teammate/meta-
  change/slump event (see below), not just live team-switch rumors.
- **`liquidity_provider`** -- "constantly maintain bids and asks." Does
  **not** go through the normal buy-or-sell dispatch at all --
  `trading.py`'s `_run_market_maker()` gives each liquidity-provider bot a
  fixed set of players (assigned once, `mm_players_per_bot=4`) and, every
  round it acts, quotes a small resting buy below the current price and
  (once it holds any inventory) a resting sell above it. It doesn't chase
  signals; continuous two-sided depth is the point, not direction.

Bots' auction-time behavior maps onto the closest existing auction
archetype (`value_investor`->`value_investor`, `momentum_trader`->
`momentum`, `contrarian`/`news_trader`/`liquidity_provider`->
`diversified`/`random`) since the spec's Bot Types section is about
ongoing trading, not the one-shot auction.

### Tournament tiers: 36 Cash Cups + 3 FNCS + 1 Global = 40 events

`tournament.build_event_schedule()` builds an ordered 40-event season:
FNCS events are inserted after roughly every 12th Cash Cup (so ~evenly
spread through the calendar) and the Global Championship is the season
finale. `SimConfig.num_tournaments` is now a **derived property**
(`cash_cup_count + fncs_count + global_count`) rather than a settable
field -- `main.py --tournaments N` adjusts `cash_cup_count` to hit the
requested total while preserving the FNCS/Global finale.

### Three dividend-pool scenarios

`config.DIVIDEND_POOL_TIERS` holds the conservative/baseline/aggressive
pools exactly as specified (Cash Cup $200k/$300k/$450k, FNCS
$1M/$1.5M/$2M, Global $2M/$3M/$5M); `SimConfig.dividend_pool_tier` selects
one (default `"baseline"`). `SimConfig.dividend_pool_override` is an
escape hatch for a custom pool outside the three named tiers (used by
`liquidity_experiment.py`'s severe-stall scenarios).

### Money sinks: auction fee, transaction fee, Bank spread

- **Auction fee** (`auction_entry_fee_fraction`, default 1%): unchanged
  mechanism from v1, default flipped from 0% to the spec's "small ~1%,
  removed permanently." Also added: **minimum share price**
  (`min_share_price`) enforced on top of the existing zero-bid baseline
  case -- a player who *does* receive bids still can't clear below this
  floor (per-user cost is still capped at that user's cash, so nobody
  overspends their bid to hit the floor).
- **Transaction fee** (`transaction_fee_rate`, default 0.25%, per the
  spec's recommendation): new in v2. Charged to the **taker** on every
  fill -- Quick Buy/Sell, or the crossing portion of a new limit order --
  and removed permanently from the economy; the resting/maker side of any
  trade is completely unaffected (still pays/receives exactly their limit
  price). Resting buy orders now escrow `price * (1 + fee)` per share
  instead of just `price`, so the fee is always pre-funded and refunded
  correctly for any unfilled portion. `Market.transaction_fees_removed`
  and `Market.auction_fees_removed` (`Market.total_fees_removed`) track
  both sinks for reconciliation; both show up in `economy_metrics.csv`
  and the summary report's inflation section.
- **Bank spread**: unchanged (10% default, `bank_spread`).
- **Treasury yield / cosmetics**: per the spec's own decision, treasury
  yield is NOT enabled (`cash_yield_rate_per_tournament=0.0`, present only
  as an unused knob for a future "what if" run); cosmetic-purchase sinks
  aren't modeled at all (out of scope for an economy simulator with no
  actual game client).

### ELO (investing skill) + seasonal points

`elo.py`, called once per tournament after that tournament's dividends
and trading rounds. Each user's "portfolio appreciation + dividend
income" for the period is measured as
`(net_worth_now - net_worth_at_last_snapshot) / net_worth_at_last_snapshot`
(net worth = cash + escrowed order cash + equity), users are ranked by
percentile across *all* participants (humans and bots together, for one
consistent scale -- reporting filters to humans for the leaderboard), and:

- **ELO** moves toward/away from the user's percentile via
  `required_percentile(elo)`: a bell-curve difficulty curve where a
  higher current ELO needs a *better* percentile just to hold flat (the
  spec's explicit requirement), and a low-ELO user only needs a modest
  showing to climb back toward 1500. `elo_k` controls the step size.
- **Seasonal points** accumulate `percentile/100 * seasonal_points_per_win_pctile`
  every tournament -- unlike ELO this never decays/reverts, so it
  naturally rewards *consistent* good showings over the season (spec:
  "reward consistent performance"). `elo.reset_seasonal_points()` exists
  for a chapter boundary (see below) but isn't called by the current
  single-chapter run.

One genuine finding from the default run: **average human ELO drifts
down while average bot ELO drifts up** (see `elo_seasonal_points.png`).
Since ELO is a zero-sum percentile ranking across humans+bots combined,
this means the permanent bot population is, on average, out-earning the
median human under the spec's default bot mix and human strategy mix --
worth a look if the intent is for skilled humans to be able to climb
ELO against a static bot population rather than against a bot population
that's structurally hard to beat.

### Chapter reset (not exercised by this Alpha run)

The spec's "Reset: Cash, Shares, Market / Keep: ELO, Historical records"
chapter-boundary behavior is **not** wired into `Simulator.run()` --
this is a single-chapter run, so there's nothing to reset yet. The pieces
that would matter are already separated to make it a small addition
later: ELO lives on `User.elo`/`elo_history` (untouched by
`elo.reset_seasonal_points()`), seasonal points live on
`User.seasonal_points` (explicitly reset by that function), and cash/
holdings/market state are all in `User`/`Market`, which a chapter-reset
routine would reinitialize while leaving `elo`/`elo_history` alone.

### Simulated news (2-3 events/tournament, 6 categories)

`dynamics.generate_news_events()` fires 2-3 events per tournament
(`news_events_per_tournament_min/max`), each drawn from
`SimConfig.news_type_weights`:

- **`roster_rumor`** -- unchanged team-switch rumor mechanic from v1, now
  fired *as one of the news-event types* (removed the old independent
  per-player-per-tournament roll) so its frequency is part of the same
  "2-3 events" budget as everything else, rather than stacking on top.
- **`retirement`** -- wires the previously-unused `retirement_probability`
  field: a player is chosen (weighted by that probability) and replaced
  **in-place** (same `player_id`, same `shares_issued`) with a fresh
  rookie via `population.make_rookie_player()` -- existing shareholders
  keep their position in the roster *slot*, but the underlying talent (and
  therefore future performance) is entirely new. `Player.is_rookie` /
  `retired_tournament` mark the replacement for anyone inspecting
  `players_metrics.csv`.
- **`duo_change`** -- immediate skill *and* sentiment shock, random sign
  (community doesn't know in advance if a duo swap helps or hurts).
- **`new_teammate`** -- similar but sentiment-only-weighted and skewed
  65% positive (new-teammate news reads as upgrade hype more often than
  not, even though the real talent effect is smaller than a duo change).
- **`performance_slump`** -- forces a strongly negative `form` value,
  i.e. a *publicly visible* bad patch going into the next event (distinct
  from the private AR(1) form process that runs every tournament
  regardless of news).
- **`meta_change`** -- one global event per firing: a random subset of
  players (split by above/below-median volatility, as a playstyle proxy)
  gets a modest skill shift in one direction, representing the
  competitive meta favoring aggressive/high-variance vs.
  consistent/low-variance playstyles for a while.

Every event bumps the affected player's `recent_news_score` (decaying
~30%/tournament), which `news_trader` reads directly, and is logged to
`news_log.csv` / the "SIMULATED NEWS" section of `summary_report.txt`.

### Expanded metrics + success criteria

`metrics.py` adds, per tournament: `cash_ratio` (cash's share of total
investor net worth), Gini coefficient (all users and humans-only),
top-10%/top-1% wealth share, trading volume as a % of market cap, and
cumulative transaction/auction fees removed. Per-user turnover (total
traded notional / starting cash) and a passive-holder flag
(`trade_count <= 2`) are computed at the end in `user_performance.csv`
(run-level, not a time series, since "how much did this person trade over
the whole season" isn't naturally a per-tournament number).

`success_criteria.py` evaluates a finished run against the spec's
"Success Metrics" section (cash ratio 15-30%, dividends 20-40% of
investor returns, and five more qualitative targets the spec doesn't give
exact numbers for -- trading activity, inflation, new-user
competitiveness, no dead assets, bot liquidity). Every check documents,
inline, the exact threshold it uses and flags clearly that thresholds
without a spec-given number are this simulator's operationalization, not
the spec's. Printed as a PASS/MARGINAL/FAIL table at the end of
`summary_report.txt`.

**Default-parameters finding**: at the spec's baseline scale, the run
typically clears 2/7 success criteria -- dividends land in the target
range, bot liquidity holds up, but **cash ratio consistently overshoots**
(drifts from ~15% right after the auction up to ~40-45% by season's end,
well above the 15-30% target -- see `cash_ratio_and_inequality.png`) and
**trading volume as a % of market cap stays well under 1%**, i.e. under
this simulator's reading of "high activity." Both are worth investigating
if 15-30%/high-activity are hard design targets: users are accumulating
dividend cash faster than the current trading intensity
(`participation_rate`, `max_trade_cash_fraction`) redeploys it. Turning
either of those knobs up (or the transaction fee down) are the most
direct levers -- see `experiments.py`'s transaction-fee and bank-spread
sweeps for how much that actually moves the needle versus other levers
like bot count.

### `experiments.py`: the spec's "Experiments to Run"

Sweeps transaction fee, bank spread, dividend-pool tier, bot count,
new-user growth rate, bot strategy mix (spec default vs. two
alternatives), and news frequency -- one axis at a time off a shared
baseline (standard one-factor-at-a-time sensitivity analysis; a full
cross-product of every value on every axis is combinatorially enormous
and not how this would actually be run in practice), plus a small 2D grid
over transaction fee x bank spread specifically, since those two are the
most directly comparable money-supply levers. Runs at a reduced-but-
proportional scale by default (`--full-scale` for the spec's exact
200/500/40 scale, much slower); writes `experiment_results.csv`, a bar
chart of success-criteria pass count per axis value, and a fee x spread
heatmap. `experiment_summary.txt` calls out the best-performing value on
each axis by success-criteria pass count.

---

## v3 update: bot/human symmetry + locked-in economics

Two changes on top of everything above, both from direct user feedback
-- see `CHANGES.md`'s "v4 -> v5" section for the full write-up. Short
version:

1. **Bots now draw strategies from the exact same distribution as
   humans** (`trading_strategy_weights`, one shared roster of 15
   archetypes) -- there is no separate bot-only mix anymore. Bots exist
   purely to keep the market from being thin; `is_bot` is bookkeeping
   only, never a behavioral switch. Validated with a 100-run batch
   (`symmetry_batch.py` + `analyze_symmetry.py`): pooled across every
   tested strategy-mix/bot-ratio combination, the ELO gap between
   original-cohort humans and bots is statistically indistinguishable
   from zero (p=0.12).
2. **Economics locked in**: seasonal points removed (investing +
   dividends only); auction fee is now a flat $10,000/participant
   (`auction_entry_fee_flat`) instead of 1% of spend; a 0.02%/event cash
   treasury yield is now live (`cash_yield_rate_per_tournament`, credited
   on liquid cash only, same mechanism as dividends); new human entrants
   are off by default (`enable_new_entrants=False`) so the population is
   fixed at 350 for the whole chapter. Dividend pools (baseline tier,
   $18.3M/season) and the 0.25% transaction fee were already correct.

**A real bug was found and fixed while verifying the dividend total**:
the auction's per-bidder share rounding could over-allocate a player's
total shares beyond `shares_issued` (found via a direct share-
conservation check, not by dividend math alone) -- fixed with an exact
largest-remainder apportionment. See `CHANGES.md` for the full
explanation; `auction.py`'s new allocation block documents the fix
in-place.
