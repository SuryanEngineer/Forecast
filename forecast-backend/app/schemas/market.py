import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class MarketSnapshotResponse(BaseModel):
    id: uuid.UUID
    gamertag: str
    real_name: str | None
    team: str | None
    region: str | None
    total_shares_outstanding: int
    ipo_price: Decimal
    last_price: Decimal
    prev_close: Decimal
    change: Decimal
    change_pct: Decimal
    volume_24h: int
    market_cap: Decimal


class PaginatedMarketSnapshotResponse(BaseModel):
    """A page of the player market -- see GET /markets' docstring for why
    this is paginated at all (the real roster is tens of thousands of
    players, not a curated handful -- shipping/rendering all of them at
    once made the Markets page unusable)."""

    items: list[MarketSnapshotResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class MarketSummaryResponse(BaseModel):
    """Market-wide aggregate stats, computed as real SQL aggregates over
    every active player -- NOT derived by summing whatever page of
    MarketSnapshotResponse the client happens to have loaded, which would
    only reflect one page's worth once the market stopped being small
    enough to fetch in one request."""

    total_market_cap: Decimal
    total_players: int
    total_volume_24h: int
    players_trading: int


class PriceHistoryPointResponse(BaseModel):
    price: Decimal
    volume: int
    recorded_at: datetime

    model_config = {"from_attributes": True}
