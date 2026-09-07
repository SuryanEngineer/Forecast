"""
Core data structures shared across the simulator.
"""

from dataclasses import dataclass, field
from itertools import count

_order_ids = count(1)
_trade_ids = count(1)


@dataclass
class Player:
    player_id: int
    name: str
    skill_rating: float          # current TRUE skill -- drifts over the season
    volatility_rating: float
    retirement_probability: float
    shares_issued: int

    # ---- market state (mutated during the sim) ----
    last_trade_price: float = 10.0

    # ---- "real Fortnite scene" dynamics ----
    origin_skill: float = None   # anchor skill drifts mean-revert toward
    sentiment: float = None      # community's PERCEIVED skill/hype (what
                                  # bots actually trade on) -- more volatile
                                  # than true skill, overreacts to results,
                                  # slowly corrects back toward skill_rating
    form: float = 0.0            # short-term hot-streak/slump state (AR(1),
                                  # added to skill_rating for placement only)

    # ---- team-switch rumor state ----
    rumor_active: bool = False
    rumor_direction: int = 0     # +1 = rumored to join a stronger team/lineup,
                                  # -1 = rumored to join a weaker team or leave
    rumor_rounds_left: int = 0
    rumor_magnitude: float = 0.0
    last_rumor_confirmed: bool = None  # set once a rumor resolves, for logging

    # ---- career / retirement tracking (news events) ----
    is_rookie: bool = False        # True if this player replaced a retiree mid-season
    retired_tournament: int = None  # tournament index this player_id slot last turned over

    # ---- recent news score, read by the news_trader strategy ----
    # Bumped by duo_change / new_teammate / performance_slump / meta_change
    # news events (positive = good news, negative = bad news); decays back
    # toward 0 each tournament so only genuinely RECENT news matters.
    recent_news_score: float = 0.0

    def __post_init__(self):
        if self.origin_skill is None:
            self.origin_skill = self.skill_rating
        if self.sentiment is None:
            self.sentiment = self.skill_rating

    def __repr__(self):
        return f"Player({self.player_id}, {self.name!r}, skill={self.skill_rating:.1f})"


@dataclass
class User:
    user_id: int
    name: str
    cash: float
    strategy: str  # trading strategy archetype name
    # holdings: player_id -> shares owned
    holdings: dict = field(default_factory=dict)
    # transaction_history: list of dicts describing each fill
    transaction_history: list = field(default_factory=list)

    # ---- cohort tracking (for "how do late joiners perform" analysis) ----
    joined_tournament: int = 0   # 0 = present from the initial auction
    starting_cash_at_join: float = None

    # ---- population type (spec: 300 permanent bots vs. growing human pool) ----
    is_bot: bool = False

    # ---- ELO (investing skill, separate from wealth) ----
    elo: float = 1500.0
    elo_history: list = field(default_factory=list)     # one value per tournament
    # snapshot of net worth taken just before the most recent tournament,
    # used to measure "portfolio appreciation + dividend income" for the
    # next ELO update
    prev_snapshot_net_worth: float = None

    # ---- market-making assignment (liquidity_provider bots only) ----
    mm_players: list = field(default_factory=list)

    def __post_init__(self):
        if self.starting_cash_at_join is None:
            self.starting_cash_at_join = self.cash
        if self.prev_snapshot_net_worth is None:
            self.prev_snapshot_net_worth = self.cash

    def shares_of(self, player_id: int) -> int:
        return self.holdings.get(player_id, 0)

    def net_worth(self, price_lookup) -> float:
        """price_lookup: callable(player_id) -> current price"""
        equity = sum(
            qty * price_lookup(pid) for pid, qty in self.holdings.items() if qty > 0
        )
        return self.cash + equity

    def record(self, **kwargs):
        self.transaction_history.append(kwargs)


@dataclass
class Order:
    order_id: int
    user_id: int
    player_id: int
    side: str       # "buy" or "sell"
    quantity: int    # remaining, unfilled quantity
    price: float
    timestamp: int
    placed_round: int = 0   # trading-round index, used for expiry

    @staticmethod
    def new(user_id, player_id, side, quantity, price, timestamp, placed_round=0):
        return Order(
            order_id=next(_order_ids),
            user_id=user_id,
            player_id=player_id,
            side=side,
            quantity=quantity,
            price=price,
            timestamp=timestamp,
            placed_round=placed_round,
        )


@dataclass
class Trade:
    trade_id: int
    player_id: int
    buyer_id: int   # user_id, or -1 for Bank
    seller_id: int  # user_id, or -1 for Bank
    quantity: int
    price: float
    timestamp: int

    @staticmethod
    def new(player_id, buyer_id, seller_id, quantity, price, timestamp):
        return Trade(
            trade_id=next(_trade_ids),
            player_id=player_id,
            buyer_id=buyer_id,
            seller_id=seller_id,
            quantity=quantity,
            price=price,
            timestamp=timestamp,
        )
