from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session, defer

from app.api.deps import get_optional_user
from app.db.session import get_db
from app.models.dividend import DividendLineItem, DividendPayout
from app.models.osirion import OsirionTournamentMapping
from app.models.player import Player
from app.models.tournament import PlacementResult, Tournament, TournamentEntrant, TournamentStatus
from app.models.user import User
from app.schemas.osirion import LiveLeaderboardEntry, LiveLeaderboardResponse
from app.schemas.tournament import (
    CalendarTournamentResponse,
    GameStatResponse,
    PaginatedPlacementResultResponse,
    PaginatedTeamResultResponse,
    PlacementResultResponse,
    TeamGamesResponse,
    TeamMemberResponse,
    TeamResultResponse,
    TournamentEntrantResponse,
    TournamentResponse,
    compute_tournament_phase,
)
from app.services import economic_params_service, position_service

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
def get_tournament_calendar(
    include_completed: bool = Query(False, description="Also include finished (finalized) tournaments -- the full calendar, past and upcoming."),
    db: Session = Depends(get_db),
) -> list[CalendarTournamentResponse]:
    """Every tournament that hasn't finished yet (SCHEDULED or
    RESULTS_PENDING), soonest first, with a total-dividend-pool figure for
    each -- meant to be polled every ~45s (see this response's docstring)
    so the frontend calendar updates on its own as tournaments move from
    scheduled -> in progress -> finalized, with no admin action needed.
    Registered ABOVE /{tournament_id} on purpose -- otherwise FastAPI
    would try to parse "calendar" as a tournament_id UUID and 422 first."""
    query = db.query(Tournament).filter(Tournament.is_historical_archive.is_(False))  # hidden rows never show
    if not include_completed:
        query = query.filter(Tournament.status != TournamentStatus.FINALIZED)
    tournaments = query.limit(500).all()
    # Sorted in Python rather than via SQL nulls-handling -- cheap at this
    # size (capped at 200 rows) and guarantees a stable, dialect-independent
    # chronological order with every null start_time pushed to the end,
    # instead of relying on ORDER BY ... NULLS LAST behavior.
    tournaments.sort(key=lambda t: (t.start_time is None, t.start_time or t.created_at, t.created_at))

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
    return [TournamentEntrantResponse(player_id=player.id, gamertag=player.gamertag, is_verified=player.is_verified) for _, player in rows]


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
    base_query = (
        db.query(PlacementResult, Player)
        .join(Player, Player.id == PlacementResult.player_id)
        .filter(PlacementResult.tournament_id == tournament_id)
    )
    total = base_query.count()
    rows = base_query.order_by(PlacementResult.placement.asc()).offset((page - 1) * page_size).limit(page_size).all()
    items = []
    for result, player in rows:
        item = PlacementResultResponse.model_validate(result)
        item.gamertag = player.gamertag
        item.is_verified = player.is_verified
        items.append(item)
    return PaginatedPlacementResultResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=max(1, -(-total // page_size)),
    )


def _group_teams(rows: list[tuple[PlacementResult, Player]]) -> list[list[tuple[PlacementResult, Player]]]:
    """Same-team rows (same placement + team_id) -> one group; no team_id -> each row stands alone."""
    groups: list[list[tuple[PlacementResult, Player]]] = []
    index: dict[str, int] = {}
    for result, player in rows:
        key = f"{result.placement}:{result.team_id}" if result.team_id else str(result.id)
        if key in index:
            groups[index[key]].append((result, player))
        else:
            index[key] = len(groups)
            groups.append([(result, player)])
    return groups


@router.get("/{tournament_id}/teams", response_model=PaginatedTeamResultResponse)
def get_tournament_teams(
    tournament_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
) -> PaginatedTeamResultResponse:
    """The tournament leaderboard grouped by TEAM: stats once per team, each member's dividend pool, and --
    when the caller is logged in -- their own payout and the shares they held when the tournament STARTED
    (that snapshot, not what they hold now, is what dividends are paid on)."""
    tournament = db.get(Tournament, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")

    rows = (
        db.query(PlacementResult, Player)
        .options(defer(PlacementResult.raw_stats))  # the heavy per-game JSON isn't needed for the list
        .join(Player, Player.id == PlacementResult.player_id)
        .filter(PlacementResult.tournament_id == tournament_id)
        .order_by(PlacementResult.placement.asc(), PlacementResult.team_id.asc())
        .all()
    )
    teams = _group_teams(rows)
    total = len(teams)
    page_teams = teams[(page - 1) * page_size: page * page_size]
    player_ids = [player.id for team in page_teams for _, player in team]

    payouts = {}
    if player_ids:
        payouts = {
            p.player_id: p
            for p in db.query(DividendPayout).filter(
                DividendPayout.tournament_id == tournament_id, DividendPayout.player_id.in_(player_ids)
            ).all()
        }
    my_paid: dict = {}
    my_shares: dict = {}
    if user is not None and player_ids:
        payout_ids = [p.id for p in payouts.values()]
        paid_by_payout = {}
        if payout_ids:
            paid_by_payout = {
                li.payout_id: li
                for li in db.query(DividendLineItem).filter(
                    DividendLineItem.user_id == user.id, DividendLineItem.payout_id.in_(payout_ids)
                ).all()
            }
        for pid, payout in payouts.items():
            li = paid_by_payout.get(payout.id)
            if li is not None:
                my_paid[pid] = li.amount_paid
                my_shares[pid] = li.quantity_held_snapshot
        # Not paid yet (live / finalizing): still show the stake that WILL be paid, from the ledger.
        missing = [pid for pid in player_ids if pid not in my_shares]
        if missing and tournament.start_time is not None and tournament.start_time <= datetime.now(timezone.utc):
            my_shares.update(position_service.user_holdings_at(db, user.id, missing, tournament.start_time))

    out_items: list[TeamResultResponse] = []
    my_total = Decimal("0")
    for team in page_teams:
        members = []
        team_pool = Decimal("0")
        have_pool = False
        team_paid = Decimal("0")
        have_paid = False
        team_shares = 0
        for result, player in team:
            payout = payouts.get(player.id)
            pool = payout.total_pool_amount if payout is not None else result.prize_won
            if pool is not None:
                team_pool += pool
                have_pool = True
            paid = my_paid.get(player.id)
            if paid is not None:
                team_paid += paid
                have_paid = True
            shares = my_shares.get(player.id)
            team_shares += shares or 0
            members.append(
                TeamMemberResponse(
                    player_id=player.id,
                    gamertag=player.gamertag,
                    is_verified=player.is_verified,
                    pool_amount=pool,
                    per_share_amount=payout.per_share_amount if payout is not None else None,
                    my_shares_at_start=shares,
                    my_payout=paid,
                )
            )
        first = team[0][0]
        my_total += team_paid
        out_items.append(
            TeamResultResponse(
                placement=first.placement,
                team_id=first.team_id,
                points=first.points,
                eliminations=first.eliminations,
                team_pool_amount=team_pool if have_pool else None,
                my_payout=team_paid if have_paid else None,
                my_shares_at_start=team_shares or None,
                members=members,
            )
        )

    return PaginatedTeamResultResponse(
        items=out_items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=max(1, -(-total // page_size)),
        record_date=tournament.start_time,
        my_total_payout=my_total if user is not None else None,
    )


# Osirion's per-game stat keys aren't documented/stable across seasons -- try each candidate and fall back to None.
_PLACEMENT_KEYS = ("PLACEMENT_STAT_INDEX", "PLACEMENT", "placement", "Placement")
_ELIM_KEYS = ("TEAM_ELIMS_STAT_INDEX", "PLAYER_ELIMS_STAT_INDEX", "Eliminations", "eliminations")


def _first_int(stats: dict, keys: tuple) -> int | None:
    for key in keys:
        if key in stats:
            try:
                return int(stats[key])
            except (TypeError, ValueError):
                return None
    return None


def _first_present(d: dict, keys: tuple):
    for key in keys:
        if d.get(key) is not None:
            return d[key]
    return None


@router.get("/{tournament_id}/players/{player_id}/games", response_model=TeamGamesResponse)
def get_team_games(
    tournament_id: uuid.UUID,
    player_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> TeamGamesResponse:
    """Game-by-game breakdown for the team this player played on in this tournament, from the per-game
    `sessionHistory` Osirion reports (stored verbatim in PlacementResult.raw_stats). Every raw stat is passed
    through in `stats`; the common ones (placement, eliminations, points) are also lifted out."""
    result = (
        db.query(PlacementResult)
        .filter(PlacementResult.tournament_id == tournament_id, PlacementResult.player_id == player_id)
        .one_or_none()
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No result for that player in this tournament")

    mates = [(result, db.get(Player, player_id))]
    if result.team_id:
        for other, p in (
            db.query(PlacementResult, Player)
            .options(defer(PlacementResult.raw_stats))
            .join(Player, Player.id == PlacementResult.player_id)
            .filter(
                PlacementResult.tournament_id == tournament_id,
                PlacementResult.team_id == result.team_id,
                PlacementResult.placement == result.placement,
                PlacementResult.player_id != player_id,
            )
            .all()
        ):
            mates.append((other, p))

    raw = result.raw_stats or {}
    games: list[GameStatResponse] = []
    for i, session in enumerate(raw.get("sessionHistory") or [], start=1):
        stats = session.get("trackedStats") or {}
        pts = session.get("pointsEarned")
        if pts is None:
            pts = session.get("score")
        try:
            pts_dec = Decimal(str(pts)) if pts is not None else None
        except Exception:  # noqa: BLE001
            pts_dec = None
        ended = _first_present(session, ("endTime", "endedAt", "sessionEndTime", "endDate", "date"))
        games.append(
            GameStatResponse(
                game=i,
                session_id=str(_first_present(session, ("sessionId", "matchId", "id")) or "") or None,
                ended_at=str(ended) if ended is not None else None,
                placement=_first_int(stats, _PLACEMENT_KEYS),
                eliminations=_first_int(stats, _ELIM_KEYS),
                points=pts_dec,
                stats={k: v for k, v in stats.items()},
            )
        )

    placements = [g.placement for g in games if g.placement is not None]
    elims = [g.eliminations for g in games if g.eliminations is not None]
    pts_list = [g.points for g in games if g.points is not None]
    return TeamGamesResponse(
        tournament_id=tournament_id,
        placement=result.placement,
        members=[
            TeamMemberResponse(player_id=p.id, gamertag=p.gamertag, is_verified=p.is_verified)
            for _, p in mates
            if p is not None
        ],
        games=games,
        games_played=len(games),
        wins=sum(1 for x in placements if x == 1),
        avg_placement=(Decimal(sum(placements)) / Decimal(len(placements))).quantize(Decimal("0.01")) if placements else None,
        total_eliminations=sum(elims) if elims else None,
        total_points=sum(pts_list, Decimal("0")) if pts_list else None,
        best_placement=min(placements) if placements else None,
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
        phase=compute_tournament_phase(tournament.status, tournament.start_time, tournament.end_time),
        is_osirion_tracked=mapping is not None,
        window_begin_time=mapping.window_begin_time if mapping else None,
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
                is_verified=player.is_verified,
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
