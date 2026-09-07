from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class PlatformParameterResponse(BaseModel):
    key: str
    value: Decimal
    description: str | None
    updated_at: datetime

    model_config = {"from_attributes": True}


class PlatformParameterUpdateRequest(BaseModel):
    value: Decimal


class DividendCurveEntryResponse(BaseModel):
    placement: int
    pool_fraction: Decimal

    model_config = {"from_attributes": True}


class DividendCurveEntryUpdateRequest(BaseModel):
    placement: int = Field(gt=0)
    pool_fraction: Decimal = Field(ge=0, le=1)
