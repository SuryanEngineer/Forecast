from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.osirion import OsirionTournamentMapping
from app.models.player import Player
from app.models.tournament import PlacementResult, Tournament
from app.schemas.osirion import LiveLeaderboardEntry, LiveLeaderboardResponse
from app.schemas.tournament import PlacementResultResponse, TournamentResponse

router = APIRouter(prefix="/tournaments", tags=["tournaments"])


@router.get("", response_model=list[TournamentResponse])
def list_tournaments(db: Session = Depends(get_db)) -> list[TournamentResponse]:
    return db.query(Tournament).order_by(Tournament.created_at.desc()).limit(200).all()


@router.get("/{tournament_id}", response_model=TournamentResponse)
def get_tournament(tournament_id: uuid.UUID, db: Session = Depends(get_db)) -> TournamentResponse:
    tournament = db.get(Tournament, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")
    return tournament


@router.get("/{tournament_id}/results", response_model=list[PlacementResultResponse])
def get_tournament_results(tournament_id: uuid.UUID, db: Session = Depends(get_db)) -> list[PlacementResultResponse]:
    return (
        db.query(PlacementResult)
        .filter(PlacementResult.tournament_id == tournament_id)
        .order_by(PlacementResult.placement.asc())
        .all()
    )


@router.get("/{tournament_id}/live-leaderboard", response_model=LiveLeaderboardResponse)
def get_live_leaderboard(tournament_id: uuid.UUID, db: Session = Depends(get_db)) -> LiveLeaderboardResponse:
    """Current standings for one tournament, meant to be polled by the
    frontend while a tournament is in progress (see
    app/services/osirion_service.py -- results here reflect whatever the
    last background sync pulled, not true push/real-time; `last_synced_at`
    is what lets the UI show an honest "updated Xs ago" instead of
    claiming to be live). Works the same whether the tournament's results
    come from Osirion or manual admin entry -- `is_osirion_tracked` and
    `last_synced_at` are just null for the latter."""
    tournament = db.get(Tournament, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")

    mapping = (
        db.query(OsirionTournamentMapping).filter(OsirionTournamentMapping.tournament_id == tournament_id).one_or_none()
    )

    rows = (
        db.query(PlacementResult, Player)
        .join(Player, Player.id == PlacementResult.player_id)
        .filter(PlacementResult.tournament_id == tournament_id)
        .order_by(PlacementResult.placement.asc())
        .all()
    )

    return LiveLeaderboardResponse(
        tournament_id=tournament.id,
        tournament_name=tournament.name,
        tournament_status=tournament.status.value,
        is_osirion_tracked=mapping is not None,
        window_end_time=mapping.window_end_time if mapping else None,
        last_synced_at=mapping.last_synced_at if mapping else None,
        entries=[
            LiveLeaderboardEntry(player_id=player.id, gamertag=player.gamertag, placement=result.placement, points=result.points)
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
