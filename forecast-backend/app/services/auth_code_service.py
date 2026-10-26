"""
One-time emailed codes (6 digits) for password reset, email verification and email change.

Security properties: codes are random (secrets), stored only as a peppered SHA-256, expire after
EMAIL_CODE_EXPIRE_MINUTES, are single-use, lock after EMAIL_CODE_MAX_ATTEMPTS wrong guesses, and issuing is rate
limited per user (min seconds between sends + max per hour). Requesting a new code invalidates older ones.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.account import EmailCode


class CodeRateLimited(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _hash(purpose: str, user_id: uuid.UUID, code: str) -> str:
    return hashlib.sha256(f"{settings.JWT_SECRET_KEY}:{purpose}:{user_id}:{code}".encode()).hexdigest()


def issue_code(db: Session, user_id: uuid.UUID, purpose: str, target_email: str | None = None) -> str:
    """Creates a fresh code (invalidating older unused ones). Raises CodeRateLimited when asked too often."""
    now = _now()
    recent = (
        db.query(EmailCode).filter(EmailCode.user_id == user_id, EmailCode.purpose == purpose)
        .order_by(EmailCode.created_at.desc()).limit(settings.EMAIL_CODE_MAX_PER_HOUR + 1).all()
    )
    if recent and (now - _aware(recent[0].created_at)).total_seconds() < settings.EMAIL_CODE_MIN_RESEND_SECONDS:
        raise CodeRateLimited("Please wait a moment before requesting another code.")
    in_last_hour = [c for c in recent if (now - _aware(c.created_at)).total_seconds() < 3600]
    if len(in_last_hour) >= settings.EMAIL_CODE_MAX_PER_HOUR:
        raise CodeRateLimited("Too many codes requested. Try again in a little while.")

    for old in db.query(EmailCode).filter(
        EmailCode.user_id == user_id, EmailCode.purpose == purpose, EmailCode.used_at.is_(None)
    ).all():
        old.used_at = now
    code = f"{secrets.randbelow(1_000_000):06d}"
    db.add(EmailCode(
        id=uuid.uuid4(), user_id=user_id, purpose=purpose, code_hash=_hash(purpose, user_id, code),
        target_email=target_email, expires_at=now + timedelta(minutes=settings.EMAIL_CODE_EXPIRE_MINUTES),
    ))
    db.flush()
    return code


def verify_code(db: Session, user_id: uuid.UUID, purpose: str, code: str) -> EmailCode | None:
    """Returns the consumed EmailCode row if `code` is the user's current valid code, else None (and counts the
    failed attempt, burning the code after too many)."""
    code = (code or "").strip()
    row = (
        db.query(EmailCode)
        .filter(EmailCode.user_id == user_id, EmailCode.purpose == purpose, EmailCode.used_at.is_(None))
        .order_by(EmailCode.created_at.desc()).first()
    )
    now = _now()
    if row is None or _aware(row.expires_at) < now or row.attempts >= settings.EMAIL_CODE_MAX_ATTEMPTS:
        return None
    if not secrets.compare_digest(row.code_hash, _hash(purpose, user_id, code)):
        row.attempts += 1
        if row.attempts >= settings.EMAIL_CODE_MAX_ATTEMPTS:
            row.used_at = now
        db.flush()
        return None
    row.used_at = now
    db.flush()
    return row
