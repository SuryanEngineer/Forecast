from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.ttl_cache import cached_call
from app.db.session import get_db
from app.schemas.leaderboard import LeaderboardEntryResponse
from app.services import leaderboard_service, public_profile_service

router = APIRouter(prefix="/leaderboard", tags=["leaderboard"])


@router.get("", response_model=list[LeaderboardEntryResponse])
def get_leaderboard(limit: int = 100, db: Session = Depends(get_db)) -> list[LeaderboardEntryResponse]:
    n = min(limit, 500)
    return cached_call(("leaderboard", n), 10, lambda: leaderboard_service.compute_leaderboard(db, limit=n))


@router.get("/{user_id}")
def get_investor_profile(user_id: str, hours: int = Query(0, ge=0, le=9600), db: Session = Depends(get_db)) -> dict:
    """Public, limited profile of one leaderboard investor: rank, cash, shares held, net worth over time (`hours`=0 means
    since they joined), lifetime dividends and fees. No orders, trades, activity or account details. Anyone not on the
    leaderboard (bots, the House, inactive accounts) -- or anything that is not a user id at all -- is a 404."""
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Investor not found")
    data = cached_call(("investor", str(uid), hours), 30, lambda: public_profile_service.public_profile(db, uid, hours))
    if data is None:
        raise HTTPException(status_code=404, detail="Investor not found")
    return data
