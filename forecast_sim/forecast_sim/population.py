"""
Generates the competitive player pool and the initial user pool (humans +
permanent bots).

Spec: 50 humans + 300 bots participate in the initial auction (350
participants); 150 more humans join over the season via entrants.py to
reach 200 humans + 300 bots = 500 by the end.

Bots and humans are assigned strategies from the EXACT SAME weighted
distribution (`cfg.trading_strategy_weights` for ongoing trading,
`cfg.auction_strategy_weights` for the initial auction) -- bots are not a
distinctly-skilled population, they exist purely to keep the market from
being thin. See the long comment on `trading_strategy_weights` in
config.py for why this replaced an earlier, bot-only archetype mix.
"""

import numpy as np
from .models import Player, User
from .config import SimConfig

_FIRST = ["Ace", "Blitz", "Cyro", "Dax", "Echo", "Faze", "Gio", "Hex", "Ivo",
          "Jinx", "Kato", "Loki", "Myst", "Nix", "Orin", "Pyx", "Quill",
          "Ryze", "Skye", "Trix", "Uzi", "Vex", "Wraith", "Xero", "Yuki", "Zed"]
_SUFFIX = ["", "z", "tv", "fn", "x", "yt", "gg", "os", "ex", "ii", "wave"]


def _gen_name(rng: np.random.Generator, used: set) -> str:
    while True:
        name = rng.choice(_FIRST) + rng.choice(_SUFFIX)
        if name not in used:
            used.add(name)
            return name


def _draw_skill(cfg: SimConfig, rng: np.random.Generator, n: int) -> np.ndarray:
    tail = rng.pareto(cfg.skill_pareto_shape, size=n) * cfg.skill_pareto_scale
    skill = cfg.skill_base + tail
    return np.clip(skill, 1.0, cfg.skill_max)


def generate_players(cfg: SimConfig, rng: np.random.Generator) -> list[Player]:
    """Skill ratings follow a heavy-tailed distribution: base + Pareto tail,
    so a handful of players are elite (Peterbot/Pollo-equivalent) and most
    cluster near the average / competent range."""
    skill = _draw_skill(cfg, rng, cfg.num_players)
    volatility = rng.uniform(cfg.volatility_min, cfg.volatility_max, size=cfg.num_players)
    retirement = rng.uniform(cfg.retirement_prob_min, cfg.retirement_prob_max, size=cfg.num_players)

    used_names = set()
    players = []
    for i in range(cfg.num_players):
        pid = i + 1
        name = _gen_name(rng, used_names)
        players.append(Player(
            player_id=pid,
            name=name,
            skill_rating=float(skill[i]),
            volatility_rating=float(volatility[i]),
            retirement_probability=float(retirement[i]),
            shares_issued=cfg.shares_per_player,
            last_trade_price=cfg.baseline_price,
        ))
    return players


def make_rookie_player(player_id: int, cfg: SimConfig, rng: np.random.Generator,
                        used_names: set, retired_tournament: int) -> Player:
    """A fresh rookie taking over a retired player's slot (same player_id,
    same shares_issued -- existing shareholdings/market history for that
    slot carry over, only the underlying talent resets). Used by the
    "retirement" news event in dynamics.py."""
    skill = float(_draw_skill(cfg, rng, 1)[0])
    volatility = float(rng.uniform(cfg.volatility_min, cfg.volatility_max))
    retirement = float(rng.uniform(cfg.retirement_prob_min, cfg.retirement_prob_max))
    name = _gen_name(rng, used_names)
    return Player(
        player_id=player_id,
        name=name,
        skill_rating=skill,
        volatility_rating=volatility,
        retirement_probability=retirement,
        shares_issued=cfg.shares_per_player,
        is_rookie=True,
        retired_tournament=retired_tournament,
    )


def _weighted_choice(rng: np.random.Generator, weights: dict) -> str:
    keys = list(weights.keys())
    probs = np.array(list(weights.values()), dtype=float)
    probs = probs / probs.sum()
    return rng.choice(keys, p=probs)


def generate_users(cfg: SimConfig, rng: np.random.Generator) -> list[User]:
    """Builds the initial (t=0) population: `num_initial_humans` humans
    plus `num_bots` permanent bots, all of whom take part in the initial
    auction. Liquidity-provider bots are additionally assigned a small set
    of players to make markets in (see trading.py)."""
    users = []
    uid = 0

    for _ in range(cfg.num_initial_humans):
        uid += 1
        auction_strategy = _weighted_choice(rng, cfg.auction_strategy_weights)
        trading_strategy = _weighted_choice(rng, cfg.trading_strategy_weights)
        u = User(
            user_id=uid,
            name=f"user_{uid}",
            cash=cfg.starting_cash,
            strategy=trading_strategy,
            is_bot=False,
        )
        u.auction_strategy = auction_strategy
        users.append(u)

    for _ in range(cfg.num_bots):
        uid += 1
        # Same weighted draw a human would get -- no separate bot-only
        # distribution, and no deterministic auction<->trading mapping;
        # a bot's auction-day behavior is exactly as independent of its
        # ongoing-trading strategy as a human's is.
        auction_strategy = _weighted_choice(rng, cfg.auction_strategy_weights)
        trading_strategy = _weighted_choice(rng, cfg.trading_strategy_weights)
        u = User(
            user_id=uid,
            name=f"bot_{uid}",
            cash=cfg.starting_cash,
            strategy=trading_strategy,
            is_bot=True,
        )
        u.auction_strategy = auction_strategy
        users.append(u)

    # Assign each liquidity_provider bot a fixed set of players to
    # continuously quote both sides of -- picked once, up front, so their
    # market-making presence is stable rather than jumping around.
    lp_bots = [u for u in users if u.strategy == "liquidity_provider"]
    if lp_bots:
        player_ids = list(range(1, cfg.num_players + 1))
        for u in lp_bots:
            k = min(cfg.mm_players_per_bot, len(player_ids))
            u.mm_players = list(rng.choice(player_ids, size=k, replace=False))

    return users
