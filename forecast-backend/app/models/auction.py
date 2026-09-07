"""
Player-share IPO auction.

This is the mechanism validated end-to-end in the economy simulation for
how player shares actually enter circulation -- an alternative to a
player simply IPO'ing with the House owning 100% of its shares outright
(see app/services/player_service.py, which is still what happens by
default when an admin creates a player; running it through an auction
afterward is optional but is how the simulation's locked-in economics
assume shares get distributed at chapter start).

One AuctionRound covers every player an admin adds to it at once (in the
simulation, this is "every player, once, at chapter start"). A user pays
ONE flat entry fee (see economic_params_service.py, key
'auction.entry_fee', default $10,000) to unlock bidding across every
player in the round -- not per player, per bid. Once the admin finalizes
the round, each player's shares are allocated pro-rata to that player's
bidders using exact largest-remainder apportionment (the same rounding
method used in app/engine/dividend_calculator.py, and the same one
proven correct in the forecast_sim Python simulator after a real bug was
found and fixed there), so total shares issued always sums to exactly
Player.total_shares_outstanding -- see app/services/auction_service.py
for the allocation math itself.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy import func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import GUID

MONEY = Numeric(18, 4)


class AuctionRoundStatus(str, enum.Enum):
    OPEN = "open"           # accepting joins + bids
    FINALIZED = "finalized"  # shares allocated, cash settled -- read-only from here on


class AuctionRound(Base):
    __tablename__ = "auction_rounds"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    status: Mapped[AuctionRoundStatus] = mapped_column(
        SAEnum(AuctionRoundStatus, name="auction_round_status", native_enum=True, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False, default=AuctionRoundStatus.OPEN,
    )
    created_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("users.id"), nullable=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    participants: Mapped[list["AuctionParticipant"]] = relationship(back_populates="round")
    bids: Mapped[list["AuctionBid"]] = relationship(back_populates="round")


class AuctionParticipant(Base):
    """One user's entry into one auction round -- proof the flat entry fee
    was paid (see economic_params_service.py, key 'auction.entry_fee').
    Required before that user can place any bid in this round. A user who
    never bids on anything after joining simply forfeits the entry fee
    (matches the simulation's design -- the fee is the cost of admission
    to the whole round, not refundable per-player)."""

    __tablename__ = "auction_participants"
    __table_args__ = (
        UniqueConstraint("auction_round_id", "user_id", name="uq_auction_participant_round_user"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    auction_round_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("auction_rounds.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    entry_fee_paid: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    round: Mapped["AuctionRound"] = relationship(back_populates="participants")


class AuctionBid(Base):
    """One user's cash commitment toward one player in one auction round.
    The bid amount is held (reserved, not spent -- mirrors how a limit buy
    order's cash is held, see app/services/wallet_service.py hold_funds)
    from the moment the bid is placed until the round is finalized.

    At finalization, the bidder is charged exactly `shares_won *
    clearing_price`, which is always <= `bid_amount` (share counts are
    whole numbers, so a bidder's exact fractional entitlement gets floored
    before any leftover shares are handed out -- see
    app/services/auction_service.py:finalize_round). Whatever wasn't
    needed is released back to available balance."""

    __tablename__ = "auction_bids"
    __table_args__ = (
        UniqueConstraint("auction_round_id", "user_id", "player_id", name="uq_auction_bid_round_user_player"),
        CheckConstraint("bid_amount > 0", name="ck_auction_bid_amount_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    auction_round_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("auction_rounds.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    player_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("players.id", ondelete="CASCADE"), nullable=False, index=True)
    bid_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    shares_won: Mapped[int | None] = mapped_column(Integer, nullable=True)
    amount_charged: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    round: Mapped["AuctionRound"] = relationship(back_populates="bids")
