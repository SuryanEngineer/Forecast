from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_optional_user
from app.db.session import get_db
from app.models.account import Season
from app.models.user import User
from app.services import season_service, stats_service

router = APIRouter(tags=["stats"])


@router.get("/stats/me")
def my_stats(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    data = stats_service.user_stats(db, user)
    db.commit()  # season_standings may lazily create entries
    return data


@router.get("/seasons/current")
def current_season(db: Session = Depends(get_db)) -> dict:
    """The Fortnite season we are in now (None between seasons), the next scheduled one, and the rank ladder."""
    cur, nxt = season_service.current_and_next(db)
    return {
        "season": season_service.season_dict(cur) if cur is not None else None,
        "next_season": season_service.season_dict(nxt) if nxt is not None else None,
        "ranks": [{"name": n, "min_points": m} for n, m in season_service.RANKS],
        "points_per_percent": season_service.POINTS_PER_PERCENT,
    }


# (The seasonal-points leaderboard was removed: one leaderboard, most money wins. Season rows stay only as calendar
# markers on charts.)
@router.get("/seasons")
def list_seasons(db: Session = Depends(get_db)) -> list[dict]:
    return [
        {"id": s.id, "name": s.name, "kind": s.kind, "starts_at": s.starts_at, "ends_at": s.ends_at,
         "ends_tbd": s.ends_at is None, "is_active": s.is_active, "finalized": s.finalized_at is not None}
        for s in db.query(Season).order_by(Season.starts_at.desc()).limit(50).all()
    ]
