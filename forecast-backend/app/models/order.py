import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Numeric
from sqlalchemy import Enum as SAEnum
from sqlalchemy import func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import GUID

MONEY = Numeric(18, 4)


class OrderSide(str, enum.Enum):
    BUY = "buy"
    SELL = "sell"


class OrderKind(str, enum.Enum):
    LIMIT = "limit"
    QUICK = "quick"  # market order -- fills immediately, see quick_trade_pricing.py


class OrderStatus(str, enum.Enum):
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_order_quantity_positive"),
        CheckConstraint("filled_quantity >= 0", name="ck_order_filled_non_negative"),
        CheckConstraint(
            "(order_kind = 'limit' AND limit_price IS NOT NULL) OR (order_kind = 'quick' AND limit_price IS NULL)",
            name="ck_order_limit_price_matches_kind",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    player_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("players.id", ondelete="CASCADE"), nullable=False, index=True)
    side: Mapped[OrderSide] = mapped_column(
        SAEnum(OrderSide, name="order_side", native_enum=True, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
    )
    order_kind: Mapped[OrderKind] = mapped_column(
        SAEnum(OrderKind, name="order_kind", native_enum=True, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
    )
    limit_price: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    filled_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[OrderStatus] = mapped_column(
        SAEnum(OrderStatus, name="order_status", native_enum=True, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        default=OrderStatus.OPEN,
        index=True,
    )
    is_bot: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="orders")
    player: Mapped["Player"] = relationship(back_populates="orders")


class Trade(Base):
    """One execution/fill. A single Order can produce many Trade rows
    (partial fills). `buy_order_id`/`sell_order_id` may reference a
    synthetic bot/system order id that has no `orders` row (bot liquidity
    and the SYSTEM_LIQUIDITY quick-order maker are not persisted as real
    Order rows) -- that's why they're plain UUID/text columns without a
    foreign key constraint rather than a relationship."""

    __tablename__ = "trades"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_trade_quantity_positive"),
        CheckConstraint("price > 0", name="ck_trade_price_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    player_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("players.id", ondelete="CASCADE"), nullable=False, index=True)
    price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    buyer_user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("users.id"), nullable=True)
    seller_user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("users.id"), nullable=True)
    buy_order_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    sell_order_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    buyer_is_bot: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    seller_is_bot: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    player: Mapped["Player"] = relationship()
