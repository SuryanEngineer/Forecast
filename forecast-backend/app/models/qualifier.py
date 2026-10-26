"""
Qualifier / earlier-round results for a tracked (cash-paying) Finals tournament.

Osirion exposes each round of an event (Round 1, Round 2 ... Finals) as its own leaderboard "window"; only the
cash-paying window becomes a Tournament (see osirion_service.auto_track_new_tournaments). The earlier windows are stored
here -- but ONLY for players who are already on the roster (we never create Players from a qualifier field, which is
what once grew the roster to 89k). The bots read these to judge who is likely to make the Finals and how they will
place (see app/services/qualifier_model_service.py).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import GUID, JSONType


class QualifierWindow(Base):
    """One earlier round (leaderboard window) feeding a Finals tournament, plus its resumable fetch cursor."""

    __tablename__ = "qualifier_windows"
    __table_args__ = (
        UniqueConstraint("tournament_id", "leaderboard_event_id", "leaderboard_event_window_id", name="uq_qualifier_window"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    tournament_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False, index=True)
    osirion_event_id: Mapped[str] = mapped_column(String(160), nullable=False)
    event_window_id: Mapped[str] = mapped_column(String(160), nullable=False)
    leaderboard_event_id: Mapped[str] = mapped_column(String(160), nullable=False)
    leaderboard_event_window_id: Mapped[str] = mapped_column(String(160), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    stage_index: Mapped[int] = mapped_column(Integer, nullable=False, default=1)  # 1 = earliest round
    begin_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Rank cutoff that earns the advancement token to the next round (from the payout table), when Osirion states it.
    advance_cutoff: Mapped[int | None] = mapped_column(Integer, nullable=True)
    field_estimate: Mapped[int | None] = mapped_column(Integer, nullable=True)  # total_pages x entries on page 0 (upper bound)
    total_pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_page: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    entries_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    matched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # True when we stopped at the page cap before the end of the field: players not found are NOT inferred to have
    # been eliminated (they may simply be further down than we read).
    capped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QualifierResult(Base):
    """One roster player's result in one earlier round, with their teammates for that round (duos/trios/squads)."""

    __tablename__ = "qualifier_results"
    __table_args__ = (UniqueConstraint("window_id", "player_id", name="uq_qualifier_result"),)

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    window_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("qualifier_windows.id", ondelete="CASCADE"), nullable=False, index=True)
    tournament_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False, index=True)
    player_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("players.id", ondelete="CASCADE"), nullable=False, index=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    percentile: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    points: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    team_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    team_size: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Roster players on the same team in this round (strings of Player ids); non-roster teammates are only counted in team_size.
    teammate_player_ids: Mapped[list | None] = mapped_column(JSONType(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
