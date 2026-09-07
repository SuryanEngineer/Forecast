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


class PriceHistoryPointResponse(BaseModel):
    price: Decimal
    volume: int
    recorded_at: datetime

    model_config = {"from_attributes": True}
