import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.auction import AuctionRoundStatus


class AuctionRoundResponse(BaseModel):
    id: uuid.UUID
    status: AuctionRoundStatus
    opened_at: datetime
    finalized_at: datetime | None

    model_config = {"from_attributes": True}


class AuctionParticipantResponse(BaseModel):
    id: uuid.UUID
    auction_round_id: uuid.UUID
    user_id: uuid.UUID
    entry_fee_paid: Decimal
    joined_at: datetime

    model_config = {"from_attributes": True}


class AuctionBidRequest(BaseModel):
    player_id: uuid.UUID
    bid_amount: Decimal = Field(gt=0)


class AuctionBidResponse(BaseModel):
    id: uuid.UUID
    auction_round_id: uuid.UUID
    player_id: uuid.UUID
    bid_amount: Decimal
    shares_won: int | None
    amount_charged: Decimal | None

    model_config = {"from_attributes": True}
