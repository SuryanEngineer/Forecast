"""
Search index for FINISHED open qualifier rounds (no payout, never a Tournament).

Open rounds have tens of thousands of entrants, so they are never stored in full. Live rounds are browsed through a cached
page proxy; finished rounds are indexed here only as far as a page cap (the top of the field), one row per player, with just
the name, rank and points -- enough to answer "how did <player> do in the open rounds". A throttled background pass fills
it (see app/services/open_rounds_service.py) and old rounds are dropped so the table stays small.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import GUID


class OpenRoundIndexState(Base):
    __tablename__ = "open_round_index_state"
    __table_args__ = (UniqueConstraint("leaderboard_event_id", "leaderboard_event_window_id", name="uq_open_round_state"),)

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    leaderboard_event_id: Mapped[str] = mapped_column(String(160), nullable=False)
    leaderboard_event_window_id: Mapped[str] = mapped_column(String(160), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_page: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    entries_indexed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    capped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # stopped at the page cap (deeper ranks not indexed)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OpenRoundEntry(Base):
    __tablename__ = "open_round_entries"
    __table_args__ = (UniqueConstraint("state_id", "rank", "name_lc", name="uq_open_round_entry"),)

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    state_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    name_lc: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    points: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
