import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.tournament import TournamentType


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


class RegionMultiplierResponse(BaseModel):
    region: str
    multiplier: Decimal
    updated_at: datetime

    model_config = {"from_attributes": True}


class RegionMultiplierUpdateRequest(BaseModel):
    region: str = Field(min_length=1, max_length=50)
    multiplier: Decimal = Field(ge=0, le=2)


class TournamentClassificationRuleResponse(BaseModel):
    id: uuid.UUID
    pattern: str
    # null = exclude (never auto-track a window matching this pattern)
    tournament_type: TournamentType | None
    priority: int
    is_active: bool
    description: str | None
    updated_at: datetime

    model_config = {"from_attributes": True}


class TournamentClassificationRuleCreateRequest(BaseModel):
    pattern: str = Field(min_length=1, max_length=200)
    tournament_type: TournamentType | None = None
    priority: int = 100
    is_active: bool = True
    description: str | None = None


class TournamentClassificationRuleUpdateRequest(BaseModel):
    """All fields optional -- only what's provided gets changed."""

    pattern: str | None = Field(default=None, min_length=1, max_length=200)
    tournament_type: TournamentType | None = None
    clear_tournament_type: bool = False  # explicit flag since tournament_type=None is itself meaningful (exclude)
    priority: int | None = None
    is_active: bool | None = None
    description: str | None = None
