"""
Read-side trading views for the frontend market/dashboard screens -- see
app/services/market_data_service.py for how "last price / 24h change /
volume / market cap" are derived from raw trade history. Nothing here is
authoritative economic state (that's Player/Position/Trade); this is a
reporting layer on top of it.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.player import Player
from app.schemas.market import MarketSnapshotResponse, PriceHistoryPointResponse
from app.services import market_data_service

router = APIRouter(prefix="/markets", tags=["markets"])


@router.get("", response_model=list[MarketSnapshotResponse])
def list_markets(db: Session = Depends(get_db)) -> list[MarketSnapshotResponse]:
    return market_data_service.list_market_snapshots(db)


@router.get("/{player_id}", response_model=MarketSnapshotResponse)
def get_market(player_id: uuid.UUID, db: Session = Depends(get_db)) -> MarketSnapshotResponse:
    player = db.get(Player, player_id)
    if player is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")
    return market_data_service.get_market_snapshot(db, player)


@router.get("/{player_id}/price-history", response_model=list[PriceHistoryPointResponse])
def get_price_history(player_id: uuid.UUID, limit: int = 200, db: Session = Depends(get_db)) -> list[PriceHistoryPointResponse]:
    return market_data_service.get_price_history(db, player_id, limit=min(limit, 1000))
