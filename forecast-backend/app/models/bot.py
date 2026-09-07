"""
Bot trader accounts. A BotProfile row is what turns an ordinary User row
into something app/services/bot_trading_service.py will act on -- the bot
IS a real User with a real Wallet and real Positions, going through the
exact same order_service.place_limit_order/place_quick_order path as a
human, just driven by a scheduled tick instead of a browser. See
bot_trading_service.py's module docstring for the full design rationale
(ported from, but not identical to, the validated Python economy
simulator's bot/human trading logic).

`strategy` is a plain string, not a native Postgres enum -- deliberately,
so adding a new archetype later is a pure application-code change with no
migration required (unlike the OrderKind/OrderStatus-style enums used
elsewhere, where the fixed value set IS the point).

`mm_player_ids` is only populated for the "liquidity_provider" strategy:
the small, fixed set of players that bot quotes both sides of every tick.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import GUID, JSONType


class BotProfile(Base):
    __tablename__ = "bot_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    strategy: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    mm_player_ids: Mapped[list | None] = mapped_column(JSONType(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship()
