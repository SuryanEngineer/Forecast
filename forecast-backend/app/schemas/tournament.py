import enum
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from pydantic import BaseModel, Field, computed_field

from app.models.tournament import TournamentStatus, TournamentType


class TournamentPhase(str, enum.Enum):
    """A single, server-computed source of truth for "what's this
    tournament doing right now", replacing what used to be three separate
    (and disagreeing) frontend heuristics -- CalendarRow's isLive/
    isAwaitingResults, the Tournaments tab's `status === 'results_pending'`
    filter, and LiveLeaderboard's `status === 'finalized'` check. Those all
    read the same raw `status`/`start_time`/`end_time` fields but combined
    them differently, which is how a not-yet-started tournament could show
    "Awaiting Results" in one place while a long-finished one showed
    "Live"/"Sync stalled" in another.

    `status` alone was never enough: a tournament sits at SCHEDULED or
    RESULTS_PENDING for its entire life until osirion_service.sync_tournament
    finalizes it, which can take a while (or, before that function's
    zero-match fix, could get stuck indefinitely) -- so "not finalized"
    does NOT mean "happening right now". Time is what actually answers
    that question:
      - UPCOMING: hasn't started yet (or has no known start_time).
      - LIVE: inside its event window (or the window's end is unknown),
        and not finalized yet.
      - FINALIZING: its window has ended but results haven't finished
        syncing/finalizing yet -- genuinely "wrapping up", not "upcoming"
        and not misleadingly "live".
      - COMPLETED: status is FINALIZED.
    """

    UPCOMING = "upcoming"
    LIVE = "live"
    FINALIZING = "finalizing"
    COMPLETED = "completed"


def compute_tournament_phase(status: TournamentStatus, start_time: datetime | None, end_time: datetime | None) -> TournamentPhase:
    if status == TournamentStatus.FINALIZED:
        return TournamentPhase.COMPLETED

    now = datetime.now(timezone.utc)
    if start_time is not None and start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    if end_time is not None and end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)

    if start_time is not None and start_time > now:
        return TournamentPhase.UPCOMING
    if end_time is not None and end_time <= now:
        return TournamentPhase.FINALIZING
    return TournamentPhase.LIVE


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

    @computed_field  # type: ignore[prop-decorator]
    @property
    def phase(self) -> TournamentPhase:
        return compute_tournament_phase(self.status, self.start_time, self.end_time)


class PlacementResultResponse(BaseModel):
    id: uuid.UUID
    tournament_id: uuid.UUID
    player_id: uuid.UUID
    placement: int
    points: Decimal | None
    prize_won: Decimal | None
    eliminations: int | None
    # Osirion-only (see app/models/tournament.py's PlacementResult
    # docstring) -- null for a manually/CSV-entered result.
    team_id: str | None = None
    percentile: Decimal | None = None

    model_config = {"from_attributes": True}


class PaginatedPlacementResultResponse(BaseModel):
    """A page of a tournament's placement results, ordered by placement
    ascending -- some real tournaments pay (and therefore record)
    placements thousands deep, so GET /tournaments/{id}/results always
    paginates rather than shipping every row in one response (see that
    endpoint's docstring)."""

    items: list[PlacementResultResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


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
    # How many players are known to have qualified for this tournament
    # ahead of results (see osirion_service.TournamentEntrant / GET
    # /tournaments/{id}/entrants) -- 0 until a sibling qualifier/heat
    # round has concluded and been synced, or once real results exist
    # (at that point entrants are superseded by actual placements).
    entrant_count: int = 0

    model_config = {"from_attributes": True}

    @computed_field  # type: ignore[prop-decorator]
    @property
    def phase(self) -> TournamentPhase:
        return compute_tournament_phase(self.status, self.start_time, self.end_time)


class TournamentEntrantResponse(BaseModel):
    """One player known to have qualified for a tournament, before real
    placement results exist for it -- see
    app/models/tournament.TournamentEntrant."""

    player_id: uuid.UUID
    gamertag: str
    is_verified: bool = False

    model_config = {"from_attributes": True}
