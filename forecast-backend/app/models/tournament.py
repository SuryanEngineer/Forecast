import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy import func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import GUID, JSONType

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

    # passive_deletes=True on both: without it, SQLAlchemy's ORM tries to
    # manage the delete-cascade itself by loading every related row and
    # issuing `UPDATE ... SET tournament_id = NULL` on them before deleting
    # the Tournament -- which fails outright, since tournament_id is
    # NOT NULL on both child tables. With passive_deletes=True, the ORM
    # steps aside and trusts the DB-level ondelete="CASCADE" already
    # declared on each child's tournament_id FK to do the real cascading
    # delete itself. (Discovered the hard way: scripts/reconcile_stale_tournaments.py
    # --confirm hit exactly this NOT NULL violation trying to null out
    # 16,141 dividend_payouts rows before deleting their tournament.)
    placement_results: Mapped[list["PlacementResult"]] = relationship(back_populates="tournament", passive_deletes=True)
    dividend_payouts: Mapped[list["DividendPayout"]] = relationship(back_populates="tournament", passive_deletes=True)


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

    # --- Osirion-only fields (null for manual/CSV-entered results) ---
    # `team_id` groups duos/squads (Osirion's leaderboard is per-TEAM, one
    # entry can produce more than one PlacementResult -- see
    # osirion_service.py's module docstring); `percentile` is Osirion's
    # own field, kept for display/future ranking-quality analysis.
    # `raw_stats` is the FULL per-team Osirion leaderboard entry (score,
    # sessionHistory, trackedStats -- damage/accuracy/time-alive/etc, not
    # all of which have a dedicated column here) captured verbatim at sync
    # time, specifically so nothing is lost if a future stats feature
    # wants a field this table doesn't have a column for yet, or if
    # Osirion's public beta API ever purges/rotates this tournament's data
    # (see app/models/tournament.py's TournamentResultArchive for the
    # equivalent tournament-level, not per-player, raw archive).
    team_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    percentile: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    raw_stats: Mapped[dict | None] = mapped_column(JSONType(), nullable=True)

    entered_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tournament: Mapped["Tournament"] = relationship(back_populates="placement_results")
    player: Mapped["Player"] = relationship(back_populates="placement_results")


class TournamentEntrant(Base):
    """A player known to have qualified for / be competing in a tournament
    BEFORE any placement results exist for it -- populated by
    app/services/osirion_service.py's `_seed_entrants_from_heat_windows`
    from a sibling heat/qualifier window's leaderboard once that heat has
    concluded, so the frontend can show a real field of competitors ahead
    of Finals day instead of a blank "no results yet" leaderboard. Once
    real PlacementResult rows exist for the tournament, those are the
    authoritative roster -- this table is only meaningful pre-results."""

    __tablename__ = "tournament_entrants"
    __table_args__ = (
        UniqueConstraint("tournament_id", "player_id", name="uq_tournament_entrant"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    tournament_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False, index=True)
    player_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("players.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tournament: Mapped["Tournament"] = relationship()
    player: Mapped["Player"] = relationship()


class TournamentResultArchive(Base):
    """Permanent, one-row-per-tournament snapshot of the raw Osirion data
    behind a tracked tournament -- upserted on every successful sync (see
    osirion_service.sync_tournament) and at track time, so it always holds
    the most complete data captured so far. Once a tournament finalizes,
    syncing stops touching it, so whatever's here at that point is locked
    in forever.

    This exists specifically because Osirion's public beta API gives no
    data-retention guarantee -- PlacementResult rows are already this
    app's own operational/structured view of results (used by dividends
    and the UI), but they only have columns for what we knew to capture
    when they were written. This table is the full ground-truth blob
    underneath them: if a future statistics/research feature needs a
    field nobody thought to add a column for yet, or Osirion's data for
    this tournament becomes unavailable, it can always be re-derived from
    here without ever calling Osirion again.

    `raw_tournament_metadata` is the original Osirion tournament + event
    window dict (display data, prize info, eventGroup, regions) captured
    once at track_tournament time. `raw_leaderboard_entries` is every
    entry from every page of the leaderboard as of the last successful
    sync (including entries for usernames that never matched a Player --
    unlike PlacementResult, which only has rows for matched players)."""

    __tablename__ = "tournament_result_archives"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    tournament_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    raw_tournament_metadata: Mapped[dict | None] = mapped_column(JSONType(), nullable=True)
    raw_leaderboard_entries: Mapped[list | None] = mapped_column(JSONType(), nullable=True)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    tournament: Mapped["Tournament"] = relationship()
