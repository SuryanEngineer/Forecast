"""
Mapping tables for the Osirion integration (app/services/osirion_service.py,
app/integrations/osirion_client.py). Osirion's tournament data uses Epic's
own opaque internal IDs (a tournament's real "leaderboard event id"/"window
id" pair, buried inside eventWindows[].scoreLocations[] -- see
osirion_service.py's module docstring), which have no inherent relationship
to this app's own Tournament/Player primary keys. These two tables are
that relationship, recorded once (by an admin, via POST
/admin/osirion/track-tournament) and reused on every subsequent poll.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy import func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import GUID


class OsirionTournamentMapping(Base):
    """Links one of our Tournament rows to the specific Osirion/Epic
    leaderboard this tournament's results should be pulled from. One
    internal Tournament <-> one Osirion leaderboard (a single window of a
    single event) -- if a competition has multiple rounds you want to
    track as separate payouts, create one internal Tournament (and one
    mapping) per round."""

    __tablename__ = "osirion_tournament_mappings"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    tournament_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )

    # Osirion's outer identifiers -- kept for admin display/debugging only,
    # NOT what you query the leaderboard endpoint with (see below).
    osirion_event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    osirion_event_window_id: Mapped[str] = mapped_column(String(64), nullable=False)

    # The actual query params for GET /v1/tournaments/leaderboard -- these
    # come from eventWindows[].scoreLocations[].leaderboardEventId /
    # .leaderboardEventWindowId (usually the entry with isMain=true), NOT
    # the tournament/window ids above. See osirion_service.track_tournament.
    leaderboard_event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    leaderboard_event_window_id: Mapped[str] = mapped_column(String(64), nullable=False)

    # Cached from Osirion at track-time, purely for admin-facing display
    # (this app's own Tournament.name/tournament_type are what everything
    # else -- pricing, dividends, the UI -- actually uses).
    osirion_display_name: Mapped[str | None] = mapped_column(String(300), nullable=True)

    window_begin_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Once this passes, the sync loop treats the tournament as over and
    # finalizes it (locks in results, triggers dividend payouts) on its
    # next pass -- see osirion_service.sync_all_tracked.
    window_end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tournament: Mapped["Tournament"] = relationship()


class OsirionPlayerMapping(Base):
    """Links an Osirion/Epic account id to one of our Player rows.
    Resolved once via a case-insensitive match against Player.gamertag
    the first time that account id is seen in a leaderboard (see
    osirion_service._match_player), then reused on every later sync --
    so a player later changing their display name doesn't break the
    match. `osirion_username` is cached only for admin debugging (e.g.
    figuring out why an account id didn't match anyone)."""

    __tablename__ = "osirion_player_mappings"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    osirion_account_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    osirion_username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    player_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("players.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    player: Mapped["Player"] = relationship()
