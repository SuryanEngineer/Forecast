from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_current_user
from app.db.session import get_db
from app.models.player import Player, Position
from app.models.user import User
from app.schemas.player import PlayerCreateRequest, PlayerResponse, PositionResponse
from app.services import market_maker_service, player_service

router = APIRouter(prefix="/players", tags=["players"])


@router.post("", response_model=PlayerResponse, status_code=status.HTTP_201_CREATED)
def create_player(
    payload: PlayerCreateRequest,
    seed_bot_liquidity: bool = True,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> PlayerResponse:
    """Admin-only: IPO a new player. `seed_bot_liquidity=true` (default)
    immediately posts a starting House bid/ask ladder so the player is
    tradeable right away -- see market_maker_service.py."""
    existing = db.query(Player).filter(Player.gamertag == payload.gamertag).one_or_none()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A player with that gamertag already exists")

    player = player_service.create_player(
        db,
        gamertag=payload.gamertag,
        real_name=payload.real_name,
        team=payload.team,
        region=payload.region,
        total_shares_outstanding=payload.total_shares_outstanding,
        ipo_price=payload.ipo_price,
        power_rating=payload.power_rating,
    )
    if seed_bot_liquidity:
        market_maker_service.post_bot_quotes(db, player)
    db.commit()
    return player


@router.get("", response_model=list[PlayerResponse])
def list_players(active_only: bool = True, db: Session = Depends(get_db)) -> list[PlayerResponse]:
    query = db.query(Player)
    if active_only:
        query = query.filter(Player.is_active.is_(True))
    return query.order_by(Player.gamertag.asc()).all()


@router.get("/{player_id}", response_model=PlayerResponse)
def get_player(player_id: uuid.UUID, db: Session = Depends(get_db)) -> PlayerResponse:
    player = db.get(Player, player_id)
    if player is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")
    return player


@router.get("/positions/me", response_model=list[PositionResponse])
def get_my_positions(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[PositionResponse]:
    """Every player this user currently holds shares in (quantity > 0).
    Cross-reference with GET /markets for current prices -- this endpoint
    only returns raw holdings, not valuations."""
    return db.query(Position).filter(Position.user_id == user.id, Position.quantity > 0).all()


@router.get("/{player_id}/position", response_model=PositionResponse)
def get_my_position(player_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> PositionResponse:
    position = (
        db.query(Position)
        .filter(Position.user_id == user.id, Position.player_id == player_id)
        .one_or_none()
    )
    if position is None:
        return PositionResponse(player_id=player_id, quantity=0, held_quantity=0, available_quantity=0, average_cost=0)
    return position
