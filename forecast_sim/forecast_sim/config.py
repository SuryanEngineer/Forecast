"""
Central configuration for the Forecast economy simulator.

Every tunable knob for an experiment lives here (or is passed in as an
override dict). Keeping it in one dataclass makes "change a parameter and
rerun" trivial, per the spec's requirement that the simulator be easy to
experiment with.

This file now implements the full "Forecast - Complete Economy, Market,
and Simulation Design Specification" (v2): a permanent 300-bot population
alongside a growing human population (50 -> 200), tiered tournaments
(Cash Cups / FNCS / Global Championship) with three dividend-pool
scenarios, a transaction fee, an auction fee, an ELO investing-skill
rating, seasonal points, and expanded simulated news. See README.md for
the full mapping from spec section -> code.
"""

from dataclasses import dataclass, field


# ---------------------------------------------------------------------
# Dividend pool scenarios (spec section "Proposed Dividend Pools").
# Keyed by tier name; values are per-event-type prize pools. Selected via
# SimConfig.dividend_pool_tier.
# ---------------------------------------------------------------------
DIVIDEND_POOL_TIERS = {
    "conservative": {"cash_cup": 200_000.0, "fncs": 1_000_000.0, "global": 2_000_000.0},
    "baseline":     {"cash_cup": 300_000.0, "fncs": 1_500_000.0, "global": 3_000_000.0},
    "aggressive":   {"cash_cup": 450_000.0, "fncs": 2_000_000.0, "global": 5_000_000.0},
}

# Suggested experiment grids (spec "Experiments to Run"). Not used directly
# by SimConfig -- experiments.py imports these to build its sweep.
TRANSACTION_FEE_GRID = [0.0, 0.001, 0.0025, 0.005, 0.01]
BANK_SPREAD_GRID = [0.05, 0.10, 0.15]
DIVIDEND_POOL_GRID = ["conservative", "baseline", "aggressive"]
BOT_COUNT_GRID = [100, 300, 500]
NEW_USER_GROWTH_GRID = [50, 150, 300]


@dataclass
class SimConfig:
    # ----- World size / population -----
    # Spec: 50 humans + 300 bots at launch (350 initial participants);
    # 150 more humans join over the season -> 200 humans + 300 bots = 500
    # final. Bots are permanent (never removed) and never grow in number.
    num_players: int = 200
    num_initial_humans: int = 50
    num_bots: int = 300
    human_entrant_growth_target: int = 150   # additional humans over the season
    shares_per_player: int = 5000
    starting_cash: float = 1_000_000.0       # every participant, human or bot

    # ----- Skill distribution -----
    # Skill ratings are drawn from a heavy-tailed distribution so a small
    # number of players are "elite" (Peterbot/Pollo-tier) and most cluster
    # around an average/competent level. We use a Pareto-shaped tail added
    # on top of a base skill so nobody is at 0.
    skill_base: float = 20.0
    skill_pareto_shape: float = 3.0   # higher = thinner tail (fewer elites)
    skill_pareto_scale: float = 25.0
    skill_max: float = 100.0

    # volatility_rating in [0.05, 1.0] controls how much randomness/upset
    # potential a player has in tournament placement.
    volatility_min: float = 0.15
    volatility_max: float = 0.90

    # retirement_probability: now WIRED (see dynamics.py news events) --
    # each tournament, a small number of "retirement" news events can fire,
    # weighted by this per-player probability, permanently replacing that
    # player with a fresh rookie.
    retirement_prob_min: float = 0.0
    retirement_prob_max: float = 0.05

    # ----- Initial auction -----
    # Fraction of starting cash each bot commits during the initial
    # auction (rest is kept as working capital for post-auction trading).
    auction_spend_fraction: float = 0.85
    # Hard per-user cap on total auction spend, as a fraction of starting
    # cash, applied on TOP of auction_spend_fraction (min of the two is
    # used). Lower this to force users to keep more dry powder.
    auction_spend_cap_fraction: float = 1.0
    baseline_price: float = 10.0  # used when a player receives zero bids
    # Minimum enforced share price at auction (spec: "Minimum share price
    # enforced"), independent of the zero-bid baseline case above -- a
    # player who DOES receive bids still can't price below this floor.
    min_share_price: float = 1.0
    # Auction entry fee (spec: "Small auction fee. Money removed
    # permanently."): a FLAT one-time fee charged to every auction
    # participant (human or bot) at the start of the initial auction,
    # deducted from their cash before their bidding budget is computed --
    # not a percentage of what they spend. Removed permanently from the
    # economy (tracked in Market.auction_fees_removed).
    auction_entry_fee_flat: float = 10_000.0

    # A single buy action (Quick Buy or a new entrant's opening positions)
    # can't demand more than this fraction of a player's currently visible
    # available supply (Bank inventory + resting sell orders) -- without
    # this, a large cash injection (e.g. a "whale" entrant) mostly just
    # fails to fill and sits as un-deployed cash, since the float per
    # player is small (5,000 shares). Forces big capital to scale into a
    # position over multiple rounds instead.
    max_liquidity_take_fraction: float = 0.6

    # ----- Bank -----
    bank_spread: float = 0.10  # spec recommends 10% (simulate 5/10/15%)

    # ----- Transaction fee (spec: money sink, "control inflation, discourage
    # spam trading"). Charged to the TAKER on every fill (Quick Buy/Sell and
    # any limit order that immediately crosses the book) -- the resting/
    # maker side is unaffected. Recommended 0.25%; simulate 0/0.1/0.25/0.5/1%.
    transaction_fee_rate: float = 0.0025

    # ----- Cash treasury yield -----
    # Interest credited on every user's LIQUID cash (not cash tied up in
    # open orders) once per tournament -- a genuine money SOURCE, exactly
    # like dividends, just proportional to cash held rather than shares
    # held. Default 0.02%/tournament -> ~0.8% over a 40-event season
    # (36 Cash Cup + 3 FNCS + 1 Global), close to the requested ~1%/season
    # figure (which assumed a 50-event season). Wired into
    # simulator.run() right after each tournament's dividends.
    cash_yield_rate_per_tournament: float = 0.0002

    # ----- New entrants (human users joining after t=0) -----
    # Models new HUMAN users discovering/joining Forecast over the season.
    # Bots are a separate, fixed, permanent population (see num_bots) and
    # never enter through this path. Each human entrant joins with a fresh
    # starting_cash balance and immediately deploys a chunk of it via its
    # assigned strategy's buy logic.
    # Default OFF: the population is fixed at 350 (50 humans + 300 bots)
    # for the whole chapter/season. Set True (or use --enable-entrants) to
    # bring back mid-season human growth.
    enable_new_entrants: bool = False
    new_entrants_min: int = 1
    new_entrants_max: int = 2
    new_entrant_cash: float = 1_000_000.0      # "the starting income"
    # Occasionally a much bigger entrant joins (a "whale" moment) -- tests
    # what a large fresh liquidity injection does to a stalled/thin market.
    new_entrant_whale_prob: float = 0.05
    new_entrant_whale_cash_multiplier: float = 8.0
    new_entrant_spend_fraction: float = 0.7      # fraction deployed immediately
    new_entrant_buy_count_min: int = 3           # positions opened on entry
    new_entrant_buy_count_max: int = 8

    # ----- Tournaments (spec: 36 Cash Cups + 3 FNCS + 1 Global = 40/chapter) -----
    cash_cup_count: int = 36
    fncs_count: int = 3
    global_count: int = 1
    dividend_pool_tier: str = "baseline"   # "conservative" | "baseline" | "aggressive"
    # Escape hatch for experiments that need an arbitrary custom pool
    # (e.g. an extreme stress test outside the three named tiers) --
    # takes priority over dividend_pool_tier when set.
    dividend_pool_override: dict = None
    payout_placements: int = 50          # how many placements get paid, per event
    payout_curve: str = "exponential"    # "exponential" | "power"
    payout_exp_decay: float = 0.90       # rank i weight = decay^(i-1)
    payout_power: float = 1.5            # rank i weight = i^-power

    # Skill vs. randomness balance in placement generation. Final
    # "performance score" = skill_rating + form + noise, noise ~ Normal(0, sigma)
    # where sigma = volatility_rating * placement_noise_scale.
    placement_noise_scale: float = 35.0

    # ----- Player skill/form dynamics ("real Fortnite scene" realism) -----
    skill_drift_std: float = 0.6
    skill_mean_reversion: float = 0.03
    form_persistence: float = 0.85
    form_noise_scale: float = 6.0

    # ----- Community sentiment ("overreaction to a single bad game") -----
    sentiment_decay_toward_skill: float = 0.25
    overreaction_factor: float = 2.5

    # ----- Team-switch rumors -----
    rumor_start_prob_per_player: float = 0.008   # per player, per tournament
    rumor_duration_min: int = 2
    rumor_duration_max: int = 5
    rumor_confirm_prob: float = 0.4
    rumor_skill_impact_min: float = 5.0
    rumor_skill_impact_max: float = 20.0
    rumor_volatility_multiplier: float = 1.8
    rumor_sentiment_shock_scale: float = 4.0

    # ----- Simulated news (spec: "Every tournament: 2-3 significant
    # events", duo changes / retirement / new teammate / roster rumors /
    # performance slump / meta changes). Roster rumors reuse the
    # team-switch rumor system above; the rest are handled in dynamics.py. -----
    news_events_per_tournament_min: int = 2
    news_events_per_tournament_max: int = 3
    news_type_weights: dict = field(default_factory=lambda: {
        "roster_rumor": 0.35,      # reuses the rumor lifecycle above
        "retirement": 0.10,        # uses each player's retirement_probability
        "duo_change": 0.20,
        "new_teammate": 0.15,
        "performance_slump": 0.15,
        "meta_change": 0.05,
    })
    duo_change_skill_impact: float = 8.0
    slump_form_shock: float = -18.0
    meta_change_skill_impact: float = 4.0

    # ----- Trading rounds between tournaments -----
    trading_rounds_per_tournament: int = 3
    participation_rate: float = 0.4
    max_trade_cash_fraction: float = 0.25
    max_trade_share_fraction: float = 0.5
    limit_order_probability: float = 0.5
    limit_order_offset: float = 0.03
    order_max_age_rounds: int = 12

    # ----- Liquidity-provider market-making -----
    mm_players_per_bot: int = 4          # how many players each LP quotes
    mm_quote_size_fraction: float = 0.05  # fraction of cash/holdings quoted
    mm_spread_offset: float = 0.02        # +/- around current price

    # ----- Strategy mix (initial auction archetypes) -----
    # Shared by EVERY participant, human or bot -- the auction doesn't
    # distinguish population type any more than the ongoing-trading roster
    # below does (see the note there for why).
    auction_strategy_weights: dict = field(default_factory=lambda: {
        "star_chaser": 0.2,
        "value_investor": 0.2,
        "diversified": 0.2,
        "momentum": 0.2,
        "random": 0.2,
    })

    # ----- Strategy mix for ongoing trading (initial cohort, new human
    # entrants, AND the permanent bot population) -----
    # IMPORTANT DESIGN DECISION: bots are NOT a separate, distinctly-
    # skilled population. Earlier revisions gave the permanent bots a
    # fixed 5-archetype mix distinct from the human roster (per the raw
    # spec's "Bot Types" section) -- that made bots systematically
    # out-earn the median human (avg bot ELO drifted up while avg human
    # ELO drifted down over a season), which isn't the point of a
    # permanent bot population. The bots exist purely so the market isn't
    # thin/small; they should behave exactly like an equivalent human
    # would, drawing from this exact same weighted distribution
    # (including value_investor / news_trader / liquidity_provider, which
    # a human could just as easily be assigned). `is_bot` is bookkeeping
    # only (lets reporting separate "permanent depth" from "the growing
    # human population") -- it changes nothing about how a user decides
    # what to trade.
    trading_strategy_weights: dict = field(default_factory=lambda: {
        "dividend_hunter": 0.09,
        "speculator": 0.09,
        "momentum_trader": 0.09,
        "contrarian": 0.07,
        "index_investor": 0.07,
        "random": 0.07,
        "panic_seller": 0.08,
        "hype_chaser": 0.08,
        "smart_money": 0.07,
        "rumor_trader": 0.07,
        "team_loyalist": 0.05,
        "scalper": 0.05,
        "value_investor": 0.06,
        "news_trader": 0.05,
        "liquidity_provider": 0.05,
    })

    # ----- ELO (investing-skill rating, separate from wealth) -----
    elo_start: float = 1500.0
    elo_k: float = 24.0
    # Higher current ELO requires a better percentile finish to gain
    # rating (bell-curve difficulty curve) -- see elo.py.
    elo_required_percentile_at_start: float = 50.0
    elo_required_percentile_at_2x: float = 85.0   # required pctile once ELO has doubled the gap to start

    # ----- Misc -----
    random_seed: int | None = 42
    output_dir: str = "output"

    # ------------------------------------------------------------------
    @property
    def num_tournaments(self) -> int:
        return self.cash_cup_count + self.fncs_count + self.global_count

    @property
    def dividend_pools(self) -> dict:
        if self.dividend_pool_override is not None:
            return self.dividend_pool_override
        return DIVIDEND_POOL_TIERS[self.dividend_pool_tier]
