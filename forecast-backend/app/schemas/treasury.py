import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.treasury import TreasuryHoldingStatus


class TreasuryPurchaseRequest(BaseModel):
    amount: Decimal = Field(gt=0)


class TreasuryRateUpdateRequest(BaseModel):
    new_annual_rate: Decimal = Field(gt=0, description="e.g. 0.04 for 4% APY")
    effective_from: date | None = None


class TreasuryInstrumentResponse(BaseModel):
    id: uuid.UUID
    name: str
    annual_rate: Decimal
    is_active: bool
    effective_from: date

    model_config = {"from_attributes": True}


class TreasuryHoldingResponse(BaseModel):
    id: uuid.UUID
    treasury_instrument_id: uuid.UUID
    principal_amount: Decimal
    accrued_interest: Decimal
    status: TreasuryHoldingStatus
    purchased_at: datetime
    redeemed_at: datetime | None

    model_config = {"from_attributes": True}
