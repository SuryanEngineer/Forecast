from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.ttl_cache import cached_call
from app.db.session import get_db
from app.schemas.leaderboard import LeaderboardEntryResponse
from app.services import leaderboard_service

router = APIRouter(prefix="/leaderboard", tags=["leaderboard"])


@router.get("", response_model=list[LeaderboardEntryResponse])
def get_leaderboard(limit: int = 100, db: Session = Depends(get_db)) -> list[LeaderboardEntryResponse]:
    n = min(limit, 500)
    return cached_call(("leaderboard", n), 10, lambda: leaderboard_service.compute_leaderboard(db, limit=n))
