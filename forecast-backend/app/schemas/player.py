import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class PlayerCreateRequest(BaseModel):
    gamertag: str = Field(min_length=1, max_length=100)
    real_name: str | None = None
    team: str | None = None
    region: str | None = None
    total_shares_outstanding: int = Field(default=10_000, gt=0)
    # Optional now: when omitted, player_service.create_player derives it
    # from power_rating instead (see ipo_price_for_rating) rather than
    # every player IPO'ing at the same flat $10. Still overridable -- pass
    # an explicit ipo_price to hand-tune one player's starting price.
    ipo_price: Decimal | None = Field(default=None, gt=0)
    power_rating: int = Field(default=65, ge=1, le=99)


class PlayerResponse(BaseModel):
    id: uuid.UUID
    gamertag: str
    real_name: str | None
    team: str | None
    region: str | None
    is_active: bool
    total_shares_outstanding: int
    ipo_price: Decimal
    power_rating: int
    created_at: datetime

    model_config = {"from_attributes": True}


class PositionResponse(BaseModel):
    player_id: uuid.UUID
    quantity: int
    held_quantity: int
    available_quantity: int
    average_cost: Decimal

    model_config = {"from_attributes": True}
