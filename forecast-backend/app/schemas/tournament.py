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


class CalendarTournamentResponse(BaseModel):
    """One row of the upcoming-tournaments calendar (GET
    /tournaments/calendar) -- meant to be polled every
    OSIRION_SYNC_INTERVAL_SECONDS so a scheduled tournament's status/payout
    updates on its own once it starts and once results start coming in,
    with no admin action needed (see osirion_service.auto_track_new_tournaments
    for how it got tracked in the first place)."""

    id: uuid.UUID
    name: str
    tournament_type: TournamentType
    region: str | None
    start_time: datetime | None
    end_time: datetime | None
    status: TournamentStatus
    # The total dividend pool this tournament pays out across every
    # placement, combined. For a FINALIZED tournament this is the exact
    # sum of every DividendPayout actually created; for one still
    # scheduled or in progress, it's a projection (fixed tier pool x
    # region multiplier, or the admin-entered prize_pool) so the calendar
    # can show a number before any results exist. Null only if neither a
    # fixed pool nor a prize_pool applies (an OTHER/MAJOR tournament with
    # no prize_pool set at all).
    total_dividend_pool: Decimal | None
    is_osirion_tracked: bool
    last_synced_at: datetime | None

    model_config = {"from_attributes": True}
