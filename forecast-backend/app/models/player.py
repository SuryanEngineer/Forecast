import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy import func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import GUID

MONEY = Numeric(18, 4)


class Player(Base):
    """A pro player as a tradeable entity. `total_shares_outstanding` is
    the fixed float of shares for this player -- all Position.quantity
    rows for this player must sum to this number (enforced in the
    service layer, not the database, since shares move between users via
    trades rather than being minted/burned per-trade)."""

    __tablename__ = "players"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    gamertag: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    real_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    team: Mapped[str | None] = mapped_column(String(150), nullable=True)
    region: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    total_shares_outstanding: Mapped[int] = mapped_column(Integer, nullable=False, default=10_000)
    ipo_price: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("10.0000"))
    # A player's competitive skill tier, roughly on a 1-99 scale (elite
    # pros in the high 90s, journeymen in the 60s-70s). Feeds two things:
    # (1) player_service.create_player derives ipo_price from this when an
    # admin doesn't supply an explicit price, so an elite player commands
    # a real premium from day one instead of every IPO starting at an
    # identical flat price; (2) bot_trading_service.py anchors each bot's
    # buy/sell bias to a "fair value" derived from ipo_price, so a
    # player's skill tier keeps exerting a persistent pull on their price
    # long after IPO, not just at creation. 65 is a neutral, roughly
    # "solid journeyman" default for existing/legacy rows that predate
    # this column.
    power_rating: Mapped[int] = mapped_column(Integer, nullable=False, default=65)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    positions: Mapped[list["Position"]] = relationship(back_populates="player")
    orders: Mapped[list["Order"]] = relationship(back_populates="player")
    price_snapshots: Mapped[list["PriceSnapshot"]] = relationship(back_populates="player")
    placement_results: Mapped[list["PlacementResult"]] = relationship(back_populates="player")


class Position(Base):
    """One user's holding of one player's shares. Unique per (user, player)
    -- quantity is adjusted in place as trades execute, `average_cost` is
    maintained for P&L display (not used by any money-movement logic).

    `held_quantity` mirrors Wallet.held_balance: shares reserved against
    the user's own open SELL orders, so the same share can't be promised
    to two different open sell orders at once. `available_quantity =
    quantity - held_quantity` is what a new sell order is checked
    against."""

    __tablename__ = "positions"
    __table_args__ = (
        UniqueConstraint("user_id", "player_id", name="uq_position_user_player"),
        CheckConstraint("quantity >= 0", name="ck_position_quantity_non_negative"),
        CheckConstraint("held_quantity >= 0", name="ck_position_held_non_negative"),
        CheckConstraint("held_quantity <= quantity", name="ck_position_held_lte_quantity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    player_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("players.id", ondelete="CASCADE"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    held_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    average_cost: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="positions")
    player: Mapped["Player"] = relationship(back_populates="positions")

    @property
    def available_quantity(self) -> int:
        return self.quantity - self.held_quantity


class PriceSnapshot(Base):
    """Point-in-time last-trade price, written every time a trade executes
    (see app/services/order_service.py). Used for price history / charts
    and as the `mid_price` fallback source for quick orders."""

    __tablename__ = "price_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    player_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("players.id", ondelete="CASCADE"), nullable=False, index=True)
    price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    volume: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    player: Mapped["Player"] = relationship(back_populates="price_snapshots")
