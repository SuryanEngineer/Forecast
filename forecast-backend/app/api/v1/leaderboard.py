from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.leaderboard import LeaderboardEntryResponse
from app.services import leaderboard_service

router = APIRouter(prefix="/leaderboard", tags=["leaderboard"])


@router.get("", response_model=list[LeaderboardEntryResponse])
def get_leaderboard(limit: int = 100, db: Session = Depends(get_db)) -> list[LeaderboardEntryResponse]:
    return leaderboard_service.compute_leaderboard(db, limit=min(limit, 500))
