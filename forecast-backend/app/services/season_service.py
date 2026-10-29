"""
Seasons + Seasonal Points (SP) + ranked tiers.

A season is a time window (normally one Fortnite competitive season). Everyone's *start value* is their net worth at
the moment they enter the season (everyone existing at season open; later signups when first seen). During the
season:

    return %  = (current net worth - start value) / start value x 100
    SP        = max(0, round(POINTS_PER_PERCENT x return %))

so SP starts at 0 each season, grows as your portfolio outperforms your starting value, and *falls* (dropping your
rank) when you lose money -- but never below 0. Ranks are looked up from SP via RANKS. When the season ends it is
finalized: final value/points/rank/position are stored on each SeasonEntry (history), and the next season starts
everyone back at 0 SP.

All numbers below are tunable constants.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.account import Season, SeasonEntry
from app.models.user import User
from app.services import portfolio_service

POINTS_PER_PERCENT = 100  # +1% return = +100 SP

# (name, min SP) ascending. Bronze/Gold/Diamond have I-III; Unreal is a single tier.
RANKS: list[tuple[str, int]] = [
    ("Bronze I", 0), ("Bronze II", 100), ("Bronze III", 250),
    ("Gold I", 500), ("Gold II", 750), ("Gold III", 1000),
    ("Diamond I", 1500), ("Diamond II", 2000), ("Diamond III", 2500),
    ("Unreal", 4000),
]


def points_for_return(return_pct: float) -> int:
    return max(0, int(round(POINTS_PER_PERCENT * return_pct)))


def rank_for_points(points: int) -> str:
    name = RANKS[0][0]
    for rname, minimum in RANKS:
        if points >= minimum:
            name = rname
    return name


def rank_progress(points: int) -> dict:
    """Current rank, next rank and progress fraction toward it."""
    idx = 0
    for i, (_, minimum) in enumerate(RANKS):
        if points >= minimum:
            idx = i
    cur_name, cur_min = RANKS[idx]
    if idx + 1 >= len(RANKS):
        return {"rank": cur_name, "next_rank": None, "points_to_next": 0, "progress": 1.0}
    nxt_name, nxt_min = RANKS[idx + 1]
    return {
        "rank": cur_name, "next_rank": nxt_name, "points_to_next": nxt_min - points,
        "progress": max(0.0, min(1.0, (points - cur_min) / max(1, nxt_min - cur_min))),
    }


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def get_active_season(db: Session) -> Season | None:
    return db.query(Season).filter(Season.is_active.is_(True)).order_by(Season.starts_at.desc()).first()


def create_season(db: Session, name: str, starts_at: datetime, ends_at: datetime | None, activate: bool = False,
                  kind: str = "season") -> Season:
    """`ends_at=None` means the end date is not announced yet (TBD)."""
    if ends_at is not None and ends_at <= starts_at:
        raise ValueError("Season must end after it starts.")
    season = Season(id=uuid.uuid4(), name=name, starts_at=starts_at, ends_at=ends_at, is_active=False, kind=kind)
    db.add(season)
    db.flush()
    if activate:
        activate_season(db, season)
    return season


def activate_season(db: Session, season: Season) -> None:
    """Make `season` the active one (deactivating any other) and enter every eligible user with their current net
    worth as the start value."""
    for other in db.query(Season).filter(Season.is_active.is_(True), Season.id != season.id).all():
        other.is_active = False
    season.is_active = True
    db.flush()
    ensure_entries(db, season)


def ensure_entries(db: Session, season: Season, worths: dict | None = None) -> int:
    """Create a SeasonEntry (start value = current net worth) for every eligible user who lacks one."""
    worths = worths if worths is not None else portfolio_service.compute_net_worths(db)
    have = {uid for (uid,) in db.query(SeasonEntry.user_id).filter(SeasonEntry.season_id == season.id).all()}
    created = 0
    for uid, w in worths.items():
        if uid in have:
            continue
        db.add(SeasonEntry(id=uuid.uuid4(), season_id=season.id, user_id=uid, start_value=w["net_worth"]))
        created += 1
    if created:
        db.flush()
    return created


def season_standings(db: Session, season: Season, worths: dict | None = None) -> list[dict]:
    """Live standings (every entrant), sorted by SP then return %."""
    worths = worths if worths is not None else portfolio_service.compute_net_worths_cached(db)
    ensure_entries(db, season, worths)
    entries = db.query(SeasonEntry).filter(SeasonEntry.season_id == season.id).all()
    users = {u.id: u for u in db.query(User).filter(User.id.in_([e.user_id for e in entries])).all()} if entries else {}
    rows = []
    for e in entries:
        u = users.get(e.user_id)
        w = worths.get(e.user_id)
        if u is None or not u.is_active or w is None:
            continue
        start = e.start_value if e.start_value and e.start_value > 0 else Decimal("1")
        cur = w["net_worth"]
        ret = float((cur - start) / start * 100)
        sp = points_for_return(ret)
        rows.append({
            "user_id": e.user_id, "display_name": u.display_name, "tag": u.tag, "tag_color": u.tag_color,
            "start_value": e.start_value, "current_value": cur, "return_pct": ret,
            "season_points": sp, "rank_tier": rank_for_points(sp),
        })
    rows.sort(key=lambda r: (-r["season_points"], -r["return_pct"], r["display_name"].lower()))
    for i, r in enumerate(rows, start=1):
        r["position"] = i
    return rows


def finalize_season(db: Session, season: Season) -> int:
    """Freeze final results onto each entry and close the season. Returns number of entries finalized."""
    if season.finalized_at is not None:
        return 0
    worths = portfolio_service.compute_net_worths(db)
    standings = season_standings(db, season, worths)
    by_user = {r["user_id"]: r for r in standings}
    n = 0
    for e in db.query(SeasonEntry).filter(SeasonEntry.season_id == season.id).all():
        r = by_user.get(e.user_id)
        if r is None:
            continue
        e.final_value, e.final_points, e.final_rank, e.final_position = r["current_value"], r["season_points"], r["rank_tier"], r["position"]
        n += 1
    season.finalized_at = _now()
    season.is_active = False
    db.flush()
    return n


def run_rollover(db: Session) -> list[str]:
    """Idempotent housekeeping, safe to call every few minutes. Finalizes the active season when it has ended -- either
    its end date passed, or (for a season whose end is still TBD) the next season has begun -- and activates the season
    whose window is open. Returns human-readable actions taken."""
    actions: list[str] = []
    now = _now()
    active = get_active_season(db)
    if active is not None and active.ends_at is not None and _aware(active.ends_at) <= now:
        n = finalize_season(db, active)
        actions.append(f"finalized '{active.name}' ({n} entries)")
        active = None
    current = (
        db.query(Season)
        .filter(Season.finalized_at.is_(None), Season.starts_at <= now, or_(Season.ends_at.is_(None), Season.ends_at > now))
        .order_by(Season.starts_at.desc()).first()
    )
    if active is not None and current is not None and current.id != active.id and _aware(current.starts_at) > _aware(active.starts_at):
        n = finalize_season(db, active)  # a later season has started: close the old one even if its end was TBD
        actions.append(f"finalized '{active.name}' ({n} entries; '{current.name}' began)")
        active = None
    if active is None and current is not None:
        activate_season(db, current)
        actions.append(f"activated '{current.name}'")
    return actions


def current_and_next(db: Session) -> tuple[Season | None, Season | None]:
    """The active season plus the next scheduled one (soonest start after now), for the website banner."""
    now = _now()
    cur = get_active_season(db)
    nxt = (
        db.query(Season).filter(Season.finalized_at.is_(None), Season.starts_at > now, Season.is_active.is_(False))
        .order_by(Season.starts_at.asc()).first()
    )
    return cur, nxt


def season_dict(s: Season) -> dict:
    return {"id": s.id, "name": s.name, "kind": s.kind, "starts_at": s.starts_at, "ends_at": s.ends_at,
            "ends_tbd": s.ends_at is None}


def user_season_history(db: Session, user_id: uuid.UUID) -> list[dict]:
    rows = (
        db.query(SeasonEntry, Season).join(Season, Season.id == SeasonEntry.season_id)
        .filter(SeasonEntry.user_id == user_id, Season.finalized_at.isnot(None))
        .order_by(Season.starts_at.desc()).all()
    )
    return [
        {"season_id": s.id, "name": s.name, "final_points": e.final_points, "final_rank": e.final_rank,
         "final_position": e.final_position, "start_value": e.start_value, "final_value": e.final_value}
        for e, s in rows
    ]
