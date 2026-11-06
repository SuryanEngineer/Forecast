"""
Read-side trading views for the frontend market/dashboard screens -- see
app/services/market_data_service.py for how "last price / 24h change /
volume / market cap" are derived from raw trade history. Nothing here is
authoritative economic state (that's Player/Position/Trade); this is a
reporting layer on top of it.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.ttl_cache import cached_call
from app.db.session import get_db
from app.models.order import OrderSide
from app.models.player import Player
from app.schemas.market import (
    MarketSnapshotResponse,
    MarketSummaryResponse,
    OrderBookResponse,
    PaginatedMarketSnapshotResponse,
    PriceHistoryPointResponse,
    QuickQuoteResponse,
)
from app.services import book_price_service, market_data_service, order_service
from app.services.exceptions import ServiceError

router = APIRouter(prefix="/markets", tags=["markets"])

_VALID_SORTS = {"market_cap", "price", "price_asc", "price_desc", "volume", "dividends", "hot", "gainers", "losers"}


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

    def build() -> PaginatedMarketSnapshotResponse:
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

    # Everyone polling the market list shares one result for a few seconds instead of each running the queries.
    return cached_call(("markets", page, page_size, sort, (search or "").strip().lower()), 5, build)


@router.get("/summary", response_model=MarketSummaryResponse)
def get_markets_summary(db: Session = Depends(get_db)) -> MarketSummaryResponse:
    """Market-wide totals for the overview panel -- computed as real SQL
    aggregates over every active player, not by summing whatever single
    page of GET /markets the frontend happens to have loaded (which, now
    that the roster is paginated, would only reflect one page's worth)."""
    return cached_call(("markets-summary",), 15, lambda: MarketSummaryResponse(**market_data_service.get_market_summary(db)))


@router.get("/benchmark")
def get_benchmark(db: Session = Depends(get_db)) -> dict:
    """The market's projected growth rate from dividends (what an average share earns per year at today's prices)."""
    from app.services import fair_price_service

    return cached_call(("markets-benchmark",), 60, lambda: fair_price_service.benchmark(db))


@router.get("/by-ids", response_model=list[MarketSnapshotResponse])
def get_markets_by_ids(
    ids: str = Query(..., description="Comma-separated player ids (up to 150)."), db: Session = Depends(get_db)
) -> list[MarketSnapshotResponse]:
    """Snapshots for a specific set of players in one request -- the portfolio, open orders and tournament views need the
    players THEY show, not a ranked page, and used to make one request per player. Registered above /{player_id}."""
    wanted: list[uuid.UUID] = []
    for raw in ids.split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            wanted.append(uuid.UUID(raw))
        except ValueError:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Bad player id: {raw}")
    if len(wanted) > 150:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Too many ids (max 150)")
    key = ("markets-by-ids", tuple(sorted(wanted)))
    return cached_call(key, 5, lambda: [MarketSnapshotResponse(**row) for row in market_data_service.get_market_snapshots_by_ids(db, wanted)])


@router.get("/{player_id}", response_model=MarketSnapshotResponse)
def get_market(player_id: uuid.UUID, db: Session = Depends(get_db)) -> MarketSnapshotResponse:
    player = db.get(Player, player_id)
    if player is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")
    return market_data_service.get_market_snapshot(db, player)


@router.get("/{player_id}/book", response_model=OrderBookResponse)
def get_order_book(player_id: uuid.UUID, depth: int = Query(8, ge=1, le=25), db: Session = Depends(get_db)) -> OrderBookResponse:
    """Resting buy / sell orders for one player, aggregated by price. The listed price is the last trade pulled into the
    best bid / best ask (see book_price_service)."""
    depth_limit = depth
    player = db.get(Player, player_id)
    if player is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")
    book = book_price_service.book_levels(db, player_id, depth)
    book["last_trade"] = market_data_service._last_price(db, player)
    return OrderBookResponse(**book)


@router.get("/{player_id}/quote", response_model=QuickQuoteResponse)
def get_quick_quote(
    player_id: uuid.UUID,
    side: str = Query(..., pattern="^(buy|sell)$"),
    quantity: int = Query(1, ge=1, le=1_000_000),
    db: Session = Depends(get_db),
) -> QuickQuoteResponse:
    """The real price of a quick order of this size: the resting orders it would take first (best price first), then the
    House for the rest, plus the transaction fee. Read-only; this is what the order box shows as the estimate."""
    try:
        quote = order_service.quote_quick_order(db, player_id, OrderSide.BUY if side == "buy" else OrderSide.SELL, quantity)
    except ServiceError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return QuickQuoteResponse(**quote)


@router.get("/{player_id}/price-history", response_model=list[PriceHistoryPointResponse])
def get_price_history(
    player_id: uuid.UUID,
    limit: int = 200,
    range: str | None = Query(None, description="1d | 1w | 1m | all -- time-ranged, chart-ready history (one point per trade, with the opening price carried in)."),
    db: Session = Depends(get_db),
) -> list[PriceHistoryPointResponse]:
    if range is not None:
        key = range.lower() if range.lower() in {"1d", "1w", "1m", "all"} else "all"
        return market_data_service.get_price_history_range(db, player_id, key)
    return market_data_service.get_price_history(db, player_id, limit=min(limit, 1000))
