"""
Tournament + placement-result ingestion.

Per the roadmap: "start with a manual admin entry tool (fast, no
scraping fragility) before investing in automated ingestion from sources
like Liquipedia or Fortnite Tracker Network." Everything here assumes a
human (an admin) is entering results through the admin API -- see
app/api/v1/admin.py. `Tournament.result_source` exists specifically so
an automated importer can be added later (CSV bulk import is the easy
next step; a scraper or a paid tracker API is the one after that) without
changing this service's interface -- an automated importer would just
call `upsert_placement_result` the same way the admin endpoint does.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.dividend import DividendPayout
from app.models.tournament import PlacementResult, ResultSource, Tournament, TournamentStatus, TournamentType
from app.services import dividend_service


def create_tournament(
    db: Session,
    name: str,
    tournament_type: TournamentType,
    prize_pool: Decimal | None = None,
    region: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    created_by_admin_id: uuid.UUID | None = None,
    result_source: ResultSource = ResultSource.MANUAL,
) -> Tournament:
    tournament = Tournament(
        id=uuid.uuid4(),
        name=name,
        tournament_type=tournament_type,
        region=region,
        start_time=start_time,
        end_time=end_time,
        prize_pool=prize_pool,
        status=TournamentStatus.SCHEDULED,
        result_source=result_source,
        created_by_admin_id=created_by_admin_id,
    )
    db.add(tournament)
    db.flush()
    return tournament


def upsert_placement_result(
    db: Session,
    tournament_id: uuid.UUID,
    player_id: uuid.UUID,
    placement: int,
    points: Decimal | None = None,
    prize_won: Decimal | None = None,
    eliminations: int | None = None,
    raw_notes: str | None = None,
    entered_by_admin_id: uuid.UUID | None = None,
) -> PlacementResult:
    """Create or update one player's placement in a tournament. Safe to
    call repeatedly while an admin is still entering results (e.g.
    correcting a typo) -- it's only `finalize_tournament` that locks
    things in and triggers dividend payouts."""
    existing = (
        db.query(PlacementResult)
        .filter(PlacementResult.tournament_id == tournament_id, PlacementResult.player_id == player_id)
        .one_or_none()
    )
    if existing is not None:
        existing.placement = placement
        existing.points = points
        existing.prize_won = prize_won
        existing.eliminations = eliminations
        existing.raw_notes = raw_notes
        existing.entered_by_admin_id = entered_by_admin_id
        result = existing
    else:
        result = PlacementResult(
            id=uuid.uuid4(),
            tournament_id=tournament_id,
            player_id=player_id,
            placement=placement,
            points=points,
            prize_won=prize_won,
            eliminations=eliminations,
            raw_notes=raw_notes,
            entered_by_admin_id=entered_by_admin_id,
        )
        db.add(result)
    db.flush()

    tournament = db.get(Tournament, tournament_id)
    if tournament.status == TournamentStatus.SCHEDULED:
        tournament.status = TournamentStatus.RESULTS_PENDING
        db.flush()

    return result


def finalize_tournament(db: Session, tournament_id: uuid.UUID) -> list[DividendPayout]:
    """
    Admin-triggered: lock in every PlacementResult entered so far for this
    tournament and kick off dividend processing for each one. Idempotent
    -- calling this twice will not create duplicate payouts (the unique
    constraint on (tournament_id, player_id) in DividendPayout plus the
    explicit existence check below both guard against it) or re-enqueue
    jobs for payouts that already exist.
    """
    from app.jobs.tasks import enqueue_dividend_payout  # local import: jobs -> services -> here would cycle otherwise

    tournament = db.get(Tournament, tournament_id)
    if tournament is None:
        raise ValueError(f"tournament {tournament_id} not found")

    results = db.query(PlacementResult).filter(PlacementResult.tournament_id == tournament_id).all()
    if not results:
        raise ValueError("cannot finalize a tournament with no placement results entered yet")

    # How many distinct placements exist for this specific tournament --
    # i.e. what "last place" means here -- so the dividend curve's tail
    # decay (see dividend_calculator.placement_payout_fraction) can spread
    # its remaining budget across the actual size of this field, not a
    # hardcoded lobby size. All of `results` is fetched up front, above,
    # before finalizing any of them, so this count is always the complete
    # field for this tournament.
    max_placement = len(results)

    new_payouts: list[DividendPayout] = []
    for result in results:
        existing_payout = (
            db.query(DividendPayout)
            .filter(DividendPayout.tournament_id == tournament_id, DividendPayout.player_id == result.player_id)
            .one_or_none()
        )
        if existing_payout is not None:
            continue
        payout = dividend_service.create_payout_for_placement(db, tournament, result, max_placement)
        new_payouts.append(payout)

    # A real commit, not just a flush: `enqueue_dividend_payout` below may
    # run `process_dividend_payout_job` synchronously, in-line, using a
    # BRAND NEW `SessionLocal()` of its own (see app/jobs/tasks.py's module
    # docstring) whenever settings.REDIS_ENABLED is false -- which is
    # exactly the recommended single-instance production setting (see
    # app/core/config.py). A flush only makes these new payout rows
    # visible within THIS session's own open transaction; a separate
    # session/connection can't see them until this transaction actually
    # commits. Without this, every finalize immediately fails with
    # "dividend payout <id> not found" on any REDIS_ENABLED=false deploy
    # (discovered by actually running this end-to-end against a real
    # database, not just reading the code). Committing here is safe even
    # though callers (admin.py, osirion_service.py, demo_tournament_service.py)
    # also commit afterward -- a second commit on an otherwise-empty
    # transaction is a no-op.
    db.commit()

    for payout in new_payouts:
        enqueue_dividend_payout(str(payout.id))

    return new_payouts
