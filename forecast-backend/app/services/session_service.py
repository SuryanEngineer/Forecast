"""
Visit/session tracking for analytics. A "session" is a run of activity with no gap longer than SESSION_GAP_MINUTES.
Login/register opens one; the frontend heartbeat (every ~60s while the tab is visible and the user is active)
extends it and accumulates `active_seconds` (each beat adds the real elapsed time, capped, so idle/closed tabs
don't inflate time-on-site).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.account import UserSession
from app.models.user import User

SESSION_GAP_MINUTES = 30
MAX_SECONDS_PER_BEAT = 120


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def start_session(db: Session, user: User, source: str, ip: str | None, user_agent: str | None) -> UserSession:
    now = _now()
    s = UserSession(id=uuid.uuid4(), user_id=user.id, started_at=now, last_seen_at=now, source=source,
                    ip_address=(ip or "")[:64] or None, user_agent=(user_agent or "")[:300] or None)
    db.add(s)
    user.last_seen_at = now
    db.flush()
    return s


def heartbeat(db: Session, user: User, ip: str | None, user_agent: str | None) -> UserSession:
    now = _now()
    s = (
        db.query(UserSession).filter(UserSession.user_id == user.id)
        .order_by(UserSession.last_seen_at.desc()).first()
    )
    if s is None or (now - _aware(s.last_seen_at)) > timedelta(minutes=SESSION_GAP_MINUTES):
        s = start_session(db, user, "heartbeat", ip, user_agent)
    else:
        elapsed = int((now - _aware(s.last_seen_at)).total_seconds())
        s.active_seconds += max(0, min(elapsed, MAX_SECONDS_PER_BEAT))
        s.heartbeats += 1
        s.last_seen_at = now
        user.last_seen_at = now
    db.flush()
    return s
