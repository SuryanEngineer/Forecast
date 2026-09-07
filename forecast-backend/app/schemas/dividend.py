import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from app.models.dividend import DividendPayoutStatus


class DividendPayoutResponse(BaseModel):
    id: uuid.UUID
    tournament_id: uuid.UUID
    player_id: uuid.UUID
    total_pool_amount: Decimal
    platform_fee_amount: Decimal
    shares_outstanding_snapshot: int
    per_share_amount: Decimal | None
    status: DividendPayoutStatus
    created_at: datetime
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class DividendLineItemResponse(BaseModel):
    id: uuid.UUID
    payout_id: uuid.UUID
    user_id: uuid.UUID
    quantity_held_snapshot: int
    amount_paid: Decimal

    model_config = {"from_attributes": True}
