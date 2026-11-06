"""
In-app notifications: trades, order cancellations, dividends, tournaments starting / ending, and a held player winning a
game. One row per event per user (real users only, never bots or the House).

`read_at` stays NULL until the user has seen it. A notification created while the user is on the site is marked read by
the app straight after its pop-up shows; one created while they are away stays unread (red dot on the bell) until they
open the notifications panel, which reads everything at once. `ref_key` makes an event idempotent: the same event can
never notify the same user twice (unique per user).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import GUID, JSONType


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("user_id", "ref_key", name="uq_notification_user_ref"),
        Index("ix_notifications_user_created", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # trade | order_cancelled | dividend | tournament_start | tournament_end | game_win
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict | None] = mapped_column(JSONType(), nullable=True)
    ref_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
