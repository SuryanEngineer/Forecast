import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy import func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import GUID

MONEY = Numeric(18, 4)


class TournamentType(str, enum.Enum):
    CASH_CUP = "cash_cup"
    FNCS_QUALIFIER = "fncs_qualifier"
    FNCS_FINALS = "fncs_finals"
    GLOBAL_CHAMPIONSHIP = "global_championship"
    MAJOR = "major"
    OTHER = "other"


class TournamentStatus(str, enum.Enum):
    SCHEDULED = "scheduled"
    RESULTS_PENDING = "results_pending"
    FINALIZED = "finalized"   # placements entered + dividends processed


class ResultSource(str, enum.Enum):
    """How placement data got into the system. `MANUAL` is the only one
    implemented for v1 per the roadmap ('start with a manual admin entry
    tool before investing in automated ingestion'). `CSV_IMPORT` is the
    same manual-trust-boundary idea, just bulk. `API_IMPORT` is a stub
    for whenever an automated source (Liquipedia, a tracker network, or a
    scraper) gets built -- see app/services/tournament_service.py for the
    adapter interface that makes that swap possible later."""

    MANUAL = "manual"
    CSV_IMPORT = "csv_import"
    API_IMPORT = "api_import"


class Tournament(Base):
    __tablename__ = "tournaments"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    tournament_type: Mapped[TournamentType] = mapped_column(
        SAEnum(TournamentType, name="tournament_type", native_enum=True, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
    )
    region: Mapped[str | None] = mapped_column(String(50), nullable=True)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    prize_pool: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    status: Mapped[TournamentStatus] = mapped_column(
        SAEnum(TournamentStatus, name="tournament_status", native_enum=True, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False, default=TournamentStatus.SCHEDULED,
    )
    result_source: Mapped[ResultSource] = mapped_column(
        SAEnum(ResultSource, name="result_source", native_enum=True, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        default=ResultSource.MANUAL,
    )
    created_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    placement_results: Mapped[list["PlacementResult"]] = relationship(back_populates="tournament")
    dividend_payouts: Mapped[list["DividendPayout"]] = relationship(back_populates="tournament")


class PlacementResult(Base):
    """One player's result in one tournament. `prize_won` is the exact
    dollar amount that player earned (preferred, most accurate); if it's
    not known, `app/engine/dividend_calculator.py` falls back to a
    standard payout curve applied to `Tournament.prize_pool` using
    `placement`."""

    __tablename__ = "placement_results"
    __table_args__ = (
        UniqueConstraint("tournament_id", "player_id", name="uq_placement_tournament_player"),
        CheckConstraint("placement > 0", name="ck_placement_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    tournament_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False, index=True)
    player_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("players.id", ondelete="CASCADE"), nullable=False, index=True)
    placement: Mapped[int] = mapped_column(Integer, nullable=False)
    points: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    prize_won: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    eliminations: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    entered_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tournament: Mapped["Tournament"] = relationship(back_populates="placement_results")
    player: Mapped["Player"] = relationship(back_populates="placement_results")
