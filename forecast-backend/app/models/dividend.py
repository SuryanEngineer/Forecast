import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy import func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import GUID

MONEY = Numeric(18, 4)


class DividendPayoutStatus(str, enum.Enum):
    PENDING = "pending"        # created, queued for the background job
    PROCESSING = "processing"  # background job picked it up
    COMPLETED = "completed"
    FAILED = "failed"


class DividendPayout(Base):
    """One payout event: one player's placement in one tournament becomes
    one pool of money split among that player's shareholders. Created
    synchronously when an admin finalizes a placement result; the actual
    money movement happens in the background job (see app/jobs/tasks.py)
    so ingesting results never blocks on paying out potentially thousands
    of shareholders."""

    __tablename__ = "dividend_payouts"
    __table_args__ = (
        UniqueConstraint("tournament_id", "player_id", name="uq_dividend_tournament_player"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    tournament_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False, index=True)
    player_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("players.id", ondelete="CASCADE"), nullable=False, index=True)
    total_pool_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    platform_fee_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0"))
    shares_outstanding_snapshot: Mapped[int] = mapped_column(Integer, nullable=False)
    per_share_amount: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    status: Mapped[DividendPayoutStatus] = mapped_column(
        SAEnum(DividendPayoutStatus, name="dividend_payout_status", native_enum=True, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False, default=DividendPayoutStatus.PENDING, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tournament: Mapped["Tournament"] = relationship(back_populates="dividend_payouts")
    player: Mapped["Player"] = relationship()
    line_items: Mapped[list["DividendLineItem"]] = relationship(back_populates="payout")


class DividendLineItem(Base):
    """One shareholder's cut of one DividendPayout. `quantity_held_snapshot`
    is frozen at record-date (the moment the payout was created) so later
    trades of the player's shares can never retroactively change who got
    paid for a tournament that already happened."""

    __tablename__ = "dividend_line_items"
    __table_args__ = (
        UniqueConstraint("payout_id", "user_id", name="uq_dividend_line_item_payout_user"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    payout_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("dividend_payouts.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    quantity_held_snapshot: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_paid: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    ledger_entry_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("ledger_entries.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    payout: Mapped["DividendPayout"] = relationship(back_populates="line_items")
