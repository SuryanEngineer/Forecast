"""
Account-level tables: sessions/activity (analytics), one-time email codes (password reset, email
verification), daily portfolio snapshots (lifetime stats), and seasons (ranked ladder).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import GUID

MONEY = Numeric(18, 4)


class UserSession(Base):
    """One visit. Created at login/register (or when a heartbeat arrives after >30 min idle); extended by
    every heartbeat. `active_seconds` accumulates only real time between heartbeats (capped per beat), so
    a tab left open overnight doesn't count as time on site."""

    __tablename__ = "user_sessions"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    active_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    heartbeats: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="login", nullable=False)  # login | register | heartbeat


class EmailCode(Base):
    """Short one-time code sent by email. Only a SHA-256 of (purpose, user, code) is stored."""

    __tablename__ = "email_codes"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    purpose: Mapped[str] = mapped_column(String(30), nullable=False)  # password_reset | verify_email | change_email
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    target_email: Mapped[str | None] = mapped_column(String(255), nullable=True)  # for change_email: the new address
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class PortfolioSnapshot(Base):
    """End-of-day (UTC) net worth per user: powers best/worst day and the portfolio history chart."""

    __tablename__ = "portfolio_snapshots"
    __table_args__ = (UniqueConstraint("user_id", "day", name="uq_portfolio_snapshot_user_day"),)

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    day: Mapped[str] = mapped_column(String(10), nullable=False, index=True)  # 'YYYY-MM-DD'
    net_worth: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    cash: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    holdings_value: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Season(Base):
    """A ranked season (normally one Fortnite competitive season). Admin-created; at most one active."""

    __tablename__ = "seasons"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SeasonEntry(Base):
    """A user's season: the net worth they started with, then their live/final result. `start_value` is
    frozen when they first appear in the season (the season's first snapshot, or signup for later joiners)."""

    __tablename__ = "season_entries"
    __table_args__ = (UniqueConstraint("season_id", "user_id", name="uq_season_entry_user"),)

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    season_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("seasons.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    start_value: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    final_value: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    final_points: Mapped[int | None] = mapped_column(Integer, nullable=True)
    final_rank: Mapped[str | None] = mapped_column(String(20), nullable=True)
    final_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
