from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.notification import Notification
from app.models.user import User
from app.services import notification_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


class MarkReadRequest(BaseModel):
    ids: list[uuid.UUID] | None = None   # omit to mark everything read


@router.get("")
def list_notifications(
    limit: int = Query(40, ge=1, le=100), user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> dict:
    """The user's newest notifications plus how many are unread. The app polls this every few seconds while the tab is
    visible (a pop-up for anything new, then marks it read) and once on load / when the tab returns."""
    rows = (
        db.query(Notification).filter(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc()).limit(limit).all()
    )
    unread = db.query(func.count(Notification.id)).filter(Notification.user_id == user.id, Notification.read_at.is_(None)).scalar() or 0
    return {"items": [notification_service.serialize(n) for n in rows], "unread": int(unread)}


@router.post("/read")
def mark_read(payload: MarkReadRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Marks the given notifications read (or ALL of the user's, when `ids` is omitted)."""
    q = db.query(Notification).filter(Notification.user_id == user.id, Notification.read_at.is_(None))
    if payload.ids is not None:
        if not payload.ids:
            return {"updated": 0}
        q = q.filter(Notification.id.in_(payload.ids))
    updated = q.update({Notification.read_at: datetime.now(timezone.utc)}, synchronize_session=False)
    db.commit()
    return {"updated": int(updated)}
