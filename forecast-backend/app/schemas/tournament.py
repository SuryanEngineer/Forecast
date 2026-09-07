import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.tournament import TournamentStatus, TournamentType


class TournamentCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    tournament_type: TournamentType
    region: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    prize_pool: Decimal | None = Field(default=None, ge=0)


class PlacementResultRequest(BaseModel):
    player_id: uuid.UUID
    placement: int = Field(gt=0)
    points: Decimal | None = None
    prize_won: Decimal | None = Field(default=None, ge=0)
    eliminations: int | None = Field(default=None, ge=0)
    raw_notes: str | None = None


class TournamentResponse(BaseModel):
    id: uuid.UUID
    name: str
    tournament_type: TournamentType
    region: str | None
    start_time: datetime | None
    end_time: datetime | None
    prize_pool: Decimal | None
    status: TournamentStatus
    created_at: datetime

    model_config = {"from_attributes": True}


class PlacementResultResponse(BaseModel):
    id: uuid.UUID
    tournament_id: uuid.UUID
    player_id: uuid.UUID
    placement: int
    points: Decimal | None
    prize_won: Decimal | None
    eliminations: int | None

    model_config = {"from_attributes": True}
