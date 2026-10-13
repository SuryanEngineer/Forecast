"""
Read-side trading views for the frontend market/dashboard screens -- see
app/services/market_data_service.py for how "last price / 24h change /
volume / market cap" are derived from raw trade history. Nothing here is
authoritative economic state (that's Player/Position/Trade); this is a
reporting layer on top of it.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.player import Player
from app.schemas.market import (
    MarketSnapshotResponse,
    MarketSummaryResponse,
    PaginatedMarketSnapshotResponse,
    PriceHistoryPointResponse,
)
from app.services import market_data_service

router = APIRouter(prefix="/markets", tags=["markets"])

_VALID_SORTS = {"market_cap", "price", "price_asc", "price_desc", "volume", "hot", "gainers", "losers"}


@router.get("", response_model=PaginatedMarketSnapshotResponse)
def list_markets(
    page: int = Query(1, ge=1),
    page_size: int = Query(60, ge=1, le=200),
    sort: str = Query("market_cap"),
    search: str | None = Query(None, min_length=1, max_length=100),
    db: Session = Depends(get_db),
) -> PaginatedMarketSnapshotResponse:
    """Paginated -- the real roster is tens of thousands of players (every
    entrant Osirion has ever recorded a real result for across every
    tracked tournament, not a small curated list), so shipping/rendering
    all of them at once made this page unusable. Default page size 60
    (a comfortable grid for the frontend's card layout); `sort` picks
    which computed field ranks the page (see market_data_service's
    _SORT_KEYS), `search` narrows by gamertag/real_name/team before
    anything else runs."""
    if sort not in _VALID_SORTS:
        sort = "market_cap"
    items, total = market_data_service.list_market_snapshots_page(
        db, page=page, page_size=page_size, sort=sort, search=search
    )
    return PaginatedMarketSnapshotResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=max(1, -(-total // page_size)),
    )


@router.get("/summary", response_model=MarketSummaryResponse)
def get_markets_summary(db: Session = Depends(get_db)) -> MarketSummaryResponse:
    """Market-wide totals for the overview panel -- computed as real SQL
    aggregates over every active player, not by summing whatever single
    page of GET /markets the frontend happens to have loaded (which, now
    that the roster is paginated, would only reflect one page's worth)."""
    return MarketSummaryResponse(**market_data_service.get_market_summary(db))


@router.get("/{player_id}", response_model=MarketSnapshotResponse)
def get_market(player_id: uuid.UUID, db: Session = Depends(get_db)) -> MarketSnapshotResponse:
    player = db.get(Player, player_id)
    if player is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")
    return market_data_service.get_market_snapshot(db, player)


@router.get("/{player_id}/price-history", response_model=list[PriceHistoryPointResponse])
def get_price_history(player_id: uuid.UUID, limit: int = 200, db: Session = Depends(get_db)) -> list[PriceHistoryPointResponse]:
    return market_data_service.get_price_history(db, player_id, limit=min(limit, 1000))
