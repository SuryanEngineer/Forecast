"""
Forgot-password flow: request a reset link, then confirm it with a new
password. Two deliberate security choices, both standard practice:

1. `request_reset` always appears to succeed, whether or not the email
   belongs to a real account -- otherwise the endpoint becomes a free
   "does this email have an account" oracle for an attacker.
2. Only a SHA-256 hash of the token is ever stored (see
   app/models/password_reset.py) -- the raw token exists only in the
   emailed link and the confirm request, never at rest.

Tokens are single-use (`used_at`) and short-lived
(settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES, default 30 min). Requesting
a new reset doesn't invalidate older outstanding tokens for the same user
explicitly, but since each is single-use and short-lived that's a minor
gap, not a real exposure.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.models.password_reset import PasswordResetToken
from app.models.user import User
from app.services import email_service


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def request_reset(db: Session, email: str) -> None:
    user = db.query(User).filter(User.email == email).one_or_none()
    if user is None or not user.is_active:
        # Deliberately silent -- see module docstring. No token is
        # created, no email attempted, but the caller (see
        # app/api/v1/auth.py) responds identically either way.
        return

    raw_token = secrets.token_urlsafe(32)
    reset_row = PasswordResetToken(
        id=uuid.uuid4(),
        user_id=user.id,
        token_hash=_hash_token(raw_token),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES),
    )
    db.add(reset_row)
    db.commit()

    reset_link = f"{settings.FRONTEND_BASE_URL.rstrip('/')}/?reset_token={raw_token}"
    email_service.send_password_reset_email(user.email, reset_link)


def confirm_reset(db: Session, raw_token: str, new_password: str) -> bool:
    """Returns True if the password was actually changed. False means the
    token was invalid, expired, or already used -- the caller (see
    app/api/v1/auth.py) turns that into a 400 with a generic message
    (never confirms *why* it failed, to avoid leaking which case it was)."""
    token_hash = _hash_token(raw_token)
    reset_row = db.query(PasswordResetToken).filter(PasswordResetToken.token_hash == token_hash).one_or_none()

    if reset_row is None:
        return False
    if reset_row.used_at is not None:
        return False
    expires_at = reset_row.expires_at
    if expires_at.tzinfo is None:
        # SQLite (demo mode -- see app/db/types.py's module docstring for
        # the equivalent GUID/JSONType story) silently drops tzinfo on a
        # DateTime(timezone=True) column: values always go in as UTC-aware
        # (see request_reset above), so a naive value read back here is
        # always UTC, never local time. Without this, comparing it to an
        # aware `datetime.now(timezone.utc)` below raises TypeError. No-op
        # on Postgres, where expires_at is already tz-aware.
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        return False

    user = db.get(User, reset_row.user_id)
    if user is None or not user.is_active:
        return False

    user.password_hash = hash_password(new_password)
    reset_row.used_at = datetime.now(timezone.utc)
    db.commit()
    return True
