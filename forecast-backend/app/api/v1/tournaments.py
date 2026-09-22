from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.osirion import OsirionTournamentMapping
from app.models.player import Player
from app.models.tournament import PlacementResult, Tournament, TournamentEntrant, TournamentStatus
from app.schemas.osirion import LiveLeaderboardEntry, LiveLeaderboardResponse
from app.schemas.tournament import (
    CalendarTournamentResponse,
    PaginatedPlacementResultResponse,
    PlacementResultResponse,
    TournamentEntrantResponse,
    TournamentResponse,
)
from app.services import economic_params_service

router = APIRouter(prefix="/tournaments", tags=["tournaments"])


@router.get("", response_model=list[TournamentResponse])
def list_tournaments(db: Session = Depends(get_db)) -> list[TournamentResponse]:
    # Excludes is_historical_archive rows (see that column's docstring on
    # Tournament) -- those are backfilled purely for their players'
    # stock/career-history value and would otherwise flood this list (and
    # the frontend's Finalized tab, which sources from this endpoint) with
    # hundreds of already-decided historical results. A player's own
    # backfilled history is still fully visible via
    # GET /tournaments/players/{id}/history, which queries PlacementResult
    # directly and isn't filtered by this flag.
    return (
        db.query(Tournament)
        .filter(Tournament.is_historical_archive.is_(False))
        .order_by(Tournament.created_at.desc())
        .limit(200)
        .all()
    )


@router.get("/calendar", response_model=list[CalendarTournamentResponse])
def get_tournament_calendar(db: Session = Depends(get_db)) -> list[CalendarTournamentResponse]:
    """Every tournament that hasn't finished yet (SCHEDULED or
    RESULTS_PENDING), soonest first, with a total-dividend-pool figure for
    each -- meant to be polled every ~45s (see this response's docstring)
    so the frontend calendar updates on its own as tournaments move from
    scheduled -> in progress -> finalized, with no admin action needed.
    Registered ABOVE /{tournament_id} on purpose -- otherwise FastAPI
    would try to parse "calendar" as a tournament_id UUID and 422 first."""
    tournaments = (
        db.query(Tournament)
        .filter(Tournament.status != TournamentStatus.FINALIZED)
        .limit(200)
        .all()
    )
    # Sorted in Python rather than via SQL nulls-handling -- cheap at this
    # size (capped at 200 rows) and guarantees a stable, dialect-independent
    # chronological order with every null start_time pushed to the end,
    # instead of relying on ORDER BY ... NULLS LAST behavior.
    tournaments.sort(key=lambda t: (t.start_time is None, t.start_time, t.created_at))

    tournament_ids = [t.id for t in tournaments]
    mappings_by_tournament = {
        m.tournament_id: m
        for m in db.query(OsirionTournamentMapping).filter(OsirionTournamentMapping.tournament_id.in_(tournament_ids)).all()
    }
    entrant_counts: dict = {}
    if tournament_ids:
        for tournament_id, count in (
            db.query(TournamentEntrant.tournament_id, func.count(TournamentEntrant.id))
            .filter(TournamentEntrant.tournament_id.in_(tournament_ids))
            .group_by(TournamentEntrant.tournament_id)
            .all()
        ):
            entrant_counts[tournament_id] = count

    rows: list[CalendarTournamentResponse] = []
    for tournament in tournaments:
        fixed_pool = economic_params_service.get_fixed_tournament_pool(db, tournament.tournament_type)
        if fixed_pool is not None:
            region_multiplier = economic_params_service.get_region_multiplier(db, tournament.region)
            total_pool: Decimal | None = fixed_pool * region_multiplier
        else:
            total_pool = tournament.prize_pool

        mapping = mappings_by_tournament.get(tournament.id)
        rows.append(
            CalendarTournamentResponse(
                id=tournament.id,
                name=tournament.name,
                tournament_type=tournament.tournament_type,
                region=tournament.region,
                start_time=tournament.start_time,
                end_time=tournament.end_time,
                status=tournament.status,
                total_dividend_pool=total_pool,
                is_osirion_tracked=mapping is not None,
                last_synced_at=mapping.last_synced_at if mapping else None,
                entrant_count=entrant_counts.get(tournament.id, 0),
            )
        )
    db.commit()
    return rows


@router.get("/{tournament_id}/entrants", response_model=list[TournamentEntrantResponse])
def get_tournament_entrants(tournament_id: uuid.UUID, db: Session = Depends(get_db)) -> list[TournamentEntrantResponse]:
    """Players known to have qualified for this tournament, pulled from a
    sibling heat/qualifier round's leaderboard once that heat concluded
    (see osirion_service.auto_track_new_tournaments /
    _seed_entrants_from_heat_windows) -- meaningful only BEFORE real
    placement results exist. Once GET /tournaments/{id}/results has real
    rows, prefer those; this is just for showing a field of competitors
    ahead of Finals day instead of a blank leaderboard."""
    rows = (
        db.query(TournamentEntrant, Player)
        .join(Player, Player.id == TournamentEntrant.player_id)
        .filter(TournamentEntrant.tournament_id == tournament_id)
        .order_by(Player.gamertag.asc())
        .all()
    )
    return [TournamentEntrantResponse(player_id=player.id, gamertag=player.gamertag) for _, player in rows]


@router.get("/{tournament_id}", response_model=TournamentResponse)
def get_tournament(tournament_id: uuid.UUID, db: Session = Depends(get_db)) -> TournamentResponse:
    tournament = db.get(Tournament, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")
    return tournament


@router.get("/{tournament_id}/results", response_model=PaginatedPlacementResultResponse)
def get_tournament_results(
    tournament_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=200),
    db: Session = Depends(get_db),
) -> PaginatedPlacementResultResponse:
    """Paginated -- a real tournament can pay (and therefore record)
    placements thousands deep (a big-field Cash Cup, not just a small
    curated lobby), and shipping every row in one response was making the
    tournaments page unusably long. Default page size 100, matching the
    frontend's "more than 100 players -> paginate" rule."""
    base_query = db.query(PlacementResult).filter(PlacementResult.tournament_id == tournament_id)
    total = base_query.count()
    rows = base_query.order_by(PlacementResult.placement.asc()).offset((page - 1) * page_size).limit(page_size).all()
    return PaginatedPlacementResultResponse(
        items=rows,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=max(1, -(-total // page_size)),
    )


@router.get("/{tournament_id}/live-leaderboard", response_model=LiveLeaderboardResponse)
def get_live_leaderboard(
    tournament_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=200),
    db: Session = Depends(get_db),
) -> LiveLeaderboardResponse:
    """Current standings for one tournament, meant to be polled by the
    frontend while a tournament is in progress (see
    app/services/osirion_service.py -- results here reflect whatever the
    last background sync pulled, not true push/real-time; `last_synced_at`
    is what lets the UI show an honest "updated Xs ago" instead of
    claiming to be live). Works the same whether the tournament's results
    come from Osirion or manual admin entry -- `is_osirion_tracked` and
    `last_synced_at` are just null for the latter.

    Paginated -- some real tournaments place (and get PlacementResult rows
    for) thousands of competitors, not just a small curated lobby, and
    shipping every one of them on every 8s poll was both making the page
    unusably long and putting real load on the backend. Default page size
    100, matching the frontend's "more than 100 players -> paginate" rule.
    """
    tournament = db.get(Tournament, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")

    mapping = (
        db.query(OsirionTournamentMapping).filter(OsirionTournamentMapping.tournament_id == tournament_id).one_or_none()
    )

    base_query = (
        db.query(PlacementResult, Player)
        .join(Player, Player.id == PlacementResult.player_id)
        .filter(PlacementResult.tournament_id == tournament_id)
    )
    total_entries = base_query.count()
    rows = (
        base_query.order_by(PlacementResult.placement.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return LiveLeaderboardResponse(
        tournament_id=tournament.id,
        tournament_name=tournament.name,
        tournament_status=tournament.status.value,
        is_osirion_tracked=mapping is not None,
        window_end_time=mapping.window_end_time if mapping else None,
        last_synced_at=mapping.last_synced_at if mapping else None,
        total_entries=total_entries,
        page=page,
        page_size=page_size,
        total_pages=max(1, -(-total_entries // page_size)),
        entries=[
            LiveLeaderboardEntry(
                player_id=player.id,
                gamertag=player.gamertag,
                placement=result.placement,
                points=result.points,
                eliminations=result.eliminations,
            )
            for result, player in rows
        ],
    )


@router.get("/players/{player_id}/history", response_model=list[PlacementResultResponse])
def get_player_tournament_history(player_id: uuid.UUID, db: Session = Depends(get_db)) -> list[PlacementResultResponse]:
    return (
        db.query(PlacementResult)
        .filter(PlacementResult.player_id == player_id)
        .order_by(PlacementResult.created_at.desc())
        .all()
    )
