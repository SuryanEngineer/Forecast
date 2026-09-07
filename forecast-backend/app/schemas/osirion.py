from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.tournament import TournamentType


class AvailableWindowResponse(BaseModel):
    """One trackable Osirion tournament window, for an admin picker UI.
    `leaderboard_event_id`/`leaderboard_event_window_id` are opaque --
    send them back verbatim in TrackTournamentRequest, don't try to
    construct or edit them."""

    event_id: str
    event_window_id: str
    round: int
    leaderboard_event_id: str
    leaderboard_event_window_id: str
    is_main: bool
    begin_time: datetime | None
    end_time: datetime | None
    display_name: str
    regions: list[str]


class TrackTournamentRequest(BaseModel):
    """Everything needed to start tracking one Osirion window as a real
    internal Tournament. `name`/`tournament_type`/`region` are the admin's
    own call (see osirion_service.py's docstring for why) -- the rest
    should be copied verbatim from one AvailableWindowResponse returned by
    GET /admin/osirion/available-tournaments."""

    name: str = Field(min_length=1, max_length=200)
    tournament_type: TournamentType
    region: str | None = None

    event_id: str
    event_window_id: str
    round: int = 0
    leaderboard_event_id: str
    leaderboard_event_window_id: str
    is_main: bool = True
    begin_time: datetime | None = None
    end_time: datetime | None = None
    display_name: str = ""
    regions: list[str] = Field(default_factory=list)


class TrackedTournamentResponse(BaseModel):
    tournament_id: uuid.UUID
    tournament_name: str
    tournament_status: str
    osirion_display_name: str | None
    window_begin_time: datetime | None
    window_end_time: datetime | None
    last_synced_at: datetime | None

    model_config = {"from_attributes": True}


class SyncResultResponse(BaseModel):
    tournament_id: uuid.UUID
    entries_seen: int
    matched: int
    unmatched_usernames: list[str]
    finalized: bool
    error: str | None


class AutoTrackResultResponse(BaseModel):
    windows_seen: int
    tracked: int
    skipped_already_tracked: int
    skipped_unclassified: int
    skipped_season_dedup: int
    skipped_not_finals: int
    entrants_seeded: int
    errors: list[str]


class LiveLeaderboardEntry(BaseModel):
    player_id: uuid.UUID
    gamertag: str
    placement: int
    points: Decimal | None


class LiveLeaderboardResponse(BaseModel):
    tournament_id: uuid.UUID
    tournament_name: str
    tournament_status: str
    is_osirion_tracked: bool
    window_end_time: datetime | None
    last_synced_at: datetime | None
    entries: list[LiveLeaderboardEntry]
