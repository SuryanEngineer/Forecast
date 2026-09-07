import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy import func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import GUID

MONEY = Numeric(18, 4)


class LedgerEntryType(str, enum.Enum):
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    ORDER_HOLD = "order_hold"          # cash reserved for an open buy order
    ORDER_RELEASE = "order_release"    # hold released (order cancelled/expired)
    TRADE_DEBIT = "trade_debit"        # buyer pays for a fill
    TRADE_CREDIT = "trade_credit"      # seller receives proceeds of a fill
    DIVIDEND_CREDIT = "dividend_credit"
    TREASURY_BUY = "treasury_buy"
    TREASURY_REDEEM = "treasury_redeem"
    FEE = "fee"


class Wallet(Base):
    """One wallet per user. `cash_balance` is spendable cash. `held_balance`
    is cash reserved against open buy orders (still owned by the user, just
    not available to spend again) -- see app/services/wallet_service.py for
    the hold/release logic that keeps these two numbers honest."""

    __tablename__ = "wallets"
    __table_args__ = (
        CheckConstraint("cash_balance >= 0", name="ck_wallet_cash_non_negative"),
        CheckConstraint("held_balance >= 0", name="ck_wallet_held_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    cash_balance: Mapped[Decimal] = mapped_column(MONEY, default=0, nullable=False)
    held_balance: Mapped[Decimal] = mapped_column(MONEY, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="wallet")
    ledger_entries: Mapped[list["LedgerEntry"]] = relationship(back_populates="wallet", order_by="LedgerEntry.created_at")

    @property
    def available_balance(self) -> Decimal:
        """Cash actually free to spend on a new order."""
        return self.cash_balance - self.held_balance


class LedgerEntry(Base):
    """
    Append-only audit trail of every balance change. Never update or
    delete a row here -- every deposit, withdrawal, trade, dividend,
    treasury purchase/redemption, and fee gets one row, with the running
    `balance_after` recorded at write time. This is what makes wallet
    balances independently reconstructable/auditable (roadmap: audit log).
    """

    __tablename__ = "ledger_entries"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    wallet_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("wallets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entry_type: Mapped[LedgerEntryType] = mapped_column(
        SAEnum(LedgerEntryType, name="ledger_entry_type", native_enum=True, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)  # signed: + increases cash, - decreases
    balance_after: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    reference_type: Mapped[str | None] = mapped_column(String(50), nullable=True)  # e.g. "trade", "order", "dividend_payout"
    reference_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    wallet: Mapped["Wallet"] = relationship(back_populates="ledger_entries")
