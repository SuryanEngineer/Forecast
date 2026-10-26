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
    s = season_service.get_active_season(db)
    if s is None:
        return {"season": None, "ranks": [{"name": n, "min_points": m} for n, m in season_service.RANKS],
                "points_per_percent": season_service.POINTS_PER_PERCENT}
    return {
        "season": {"id": s.id, "name": s.name, "starts_at": s.starts_at, "ends_at": s.ends_at},
        "ranks": [{"name": n, "min_points": m} for n, m in season_service.RANKS],
        "points_per_percent": season_service.POINTS_PER_PERCENT,
    }


@router.get("/leaderboard/seasonal")
def seasonal_leaderboard(
    limit: int = Query(100, ge=1, le=500),
    season_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    me: User | None = Depends(get_optional_user),
) -> dict:
    """Season leaderboard (live for the active season). Returns the top `limit` plus the caller's own row if outside it."""
    if season_id is not None:
        season = db.get(Season, season_id)
        if season is None:
            raise HTTPException(status_code=404, detail="Season not found")
    else:
        season = season_service.get_active_season(db)
    if season is None:
        return {"season": None, "entries": [], "me": None}
    if season.finalized_at is not None:
        from app.models.account import SeasonEntry
        rows = []
        q = db.query(SeasonEntry, User).join(User, User.id == SeasonEntry.user_id).filter(SeasonEntry.season_id == season.id)
        for e, u in q.order_by(SeasonEntry.final_position.asc()).all():
            rows.append({"user_id": e.user_id, "display_name": u.display_name, "tag": u.tag, "tag_color": u.tag_color,
                         "start_value": e.start_value, "current_value": e.final_value,
                         "return_pct": float((e.final_value - e.start_value) / e.start_value * 100) if e.start_value and e.final_value is not None else 0.0,
                         "season_points": e.final_points, "rank_tier": e.final_rank, "position": e.final_position})
    else:
        rows = season_service.season_standings(db, season)
        db.commit()
    mine = next((r for r in rows if me is not None and r["user_id"] == me.id), None)
    return {
        "season": {"id": season.id, "name": season.name, "starts_at": season.starts_at, "ends_at": season.ends_at,
                   "finalized": season.finalized_at is not None},
        "entries": rows[:limit],
        "me": mine if mine is not None and mine["position"] > limit else None,
        "total": len(rows),
    }


@router.get("/seasons")
def list_seasons(db: Session = Depends(get_db)) -> list[dict]:
    return [
        {"id": s.id, "name": s.name, "starts_at": s.starts_at, "ends_at": s.ends_at, "is_active": s.is_active,
         "finalized": s.finalized_at is not None}
        for s in db.query(Season).order_by(Season.starts_at.desc()).limit(50).all()
    ]
