import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Numeric, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy import func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import GUID

MONEY = Numeric(18, 4)
RATE = Numeric(6, 4)  # e.g. 0.0400 = 4.00% APY


class TreasuryHoldingStatus(str, enum.Enum):
    ACTIVE = "active"
    REDEEMED = "redeemed"


class TreasuryInstrument(Base):
    """
    A single 'series' of the platform's risk-free instrument at a given
    annual rate. To change the rate, insert a NEW row with a later
    `effective_from` and set the old one's `is_active = False` -- never
    mutate `annual_rate` on an existing row, so historical accrual
    calculations always use the rate that was actually in effect on that
    date (see app/engine/treasury_calculator.py).
    """

    __tablename__ = "treasury_instruments"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False, default="Forecast T-Bill")
    annual_rate: Mapped[Decimal] = mapped_column(RATE, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False, server_default=func.current_date())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    holdings: Mapped[list["TreasuryHolding"]] = relationship(back_populates="instrument")


class TreasuryHolding(Base):
    """One user's position in the treasury instrument. Redeemable any time
    for `principal_amount + accrued_interest` (see redemption_value in
    treasury_calculator.py). `last_accrued_at` lets the accrual job be
    idempotent/resumable if it fails partway through a run."""

    __tablename__ = "treasury_holdings"
    __table_args__ = (
        CheckConstraint("principal_amount > 0", name="ck_treasury_principal_positive"),
        CheckConstraint("accrued_interest >= 0", name="ck_treasury_accrued_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    treasury_instrument_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("treasury_instruments.id"), nullable=False)
    principal_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    accrued_interest: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0"))
    status: Mapped[TreasuryHoldingStatus] = mapped_column(
        SAEnum(TreasuryHoldingStatus, name="treasury_holding_status", native_enum=True, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False, default=TreasuryHoldingStatus.ACTIVE, index=True,
    )
    purchased_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_accrued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    instrument: Mapped["TreasuryInstrument"] = relationship(back_populates="holdings")
    user: Mapped["User"] = relationship(back_populates="treasury_holdings")
    accrual_log: Mapped[list["TreasuryAccrualLog"]] = relationship(back_populates="holding")


class TreasuryAccrualLog(Base):
    """One row per accrual run per holding -- lets you audit exactly how
    much interest was credited and when, line by line."""

    __tablename__ = "treasury_accrual_log"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    holding_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("treasury_holdings.id", ondelete="CASCADE"), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    accrued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    holding: Mapped["TreasuryHolding"] = relationship(back_populates="accrual_log")
