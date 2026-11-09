"""
Forgot-password flow with emailed 6-digit codes (see auth_code_service for the code security properties).

`request_reset` always appears to succeed whether or not the email has an account (no account-discovery oracle).
`confirm_reset` checks the code, sets the new password, clears any login lockout and invalidates every previously issued login token.

(The older link/token flow -- PasswordResetToken -- is retired; its table is kept so old rows don't need a migration.)
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.user import User
from app.services import account_service, auth_code_service, email_service

PURPOSE = "password_reset"
logger = logging.getLogger("forecast.email")


@dataclass(frozen=True)
class PendingResetEmail:
    """A code that has been saved and still has to be emailed (done after the HTTP response, see deliver_reset_code)."""
    to_email: str
    code: str
    code_id: uuid.UUID


def request_reset(db: Session, email: str) -> PendingResetEmail | None:
    """Saves a new code for the account (if any) and returns what to email -- or None when there is nothing to send
    (unknown/disabled account, or asked too soon). Does NOT send: the caller schedules `deliver_reset_code` as a
    background task so the response is instant and identical either way (no account-discovery by timing)."""
    user = db.query(User).filter(func.lower(User.email) == email.strip().lower()).first()
    if user is None or not user.is_active:
        return None
    try:
        code, code_id = auth_code_service.issue_code_with_id(db, user.id, PURPOSE)
    except auth_code_service.CodeRateLimited:
        return None  # silently: same response either way
    db.commit()
    return PendingResetEmail(to_email=user.email, code=code, code_id=code_id)


def deliver_reset_code(pending: PendingResetEmail) -> None:
    """Background task: emails the code, retrying transient failures. If it still can't be delivered the saved code is
    discarded, so a broken mail provider can't use up the person's hourly allowance or invalidate a code they already
    received. Never raises."""
    try:
        ok = email_service.send_with_retry(
            lambda: email_service.send_password_reset_code(pending.to_email, pending.code), "password reset code"
        )
        if ok:
            return
        logger.error("Password-reset code for %s could not be emailed; discarding it.", pending.to_email)
        db = SessionLocal()
        try:
            auth_code_service.discard_code(db, pending.code_id)
        finally:
            db.close()
    except Exception:  # noqa: BLE001 -- a background task must not blow up
        logger.exception("deliver_reset_code crashed for %s", pending.to_email)


def confirm_reset(db: Session, email: str, code: str, new_password: str) -> bool:
    """True if the password was changed; False for a wrong/expired/used code (caller shows a generic message).
    Raises AccountError only for a weak new password (checked after the code so it can't be probed)."""
    user = db.query(User).filter(func.lower(User.email) == email.lower()).first()
    if user is None or not user.is_active:
        return False
    row = auth_code_service.verify_code(db, user.id, PURPOSE, code)
    if row is None:
        db.commit()  # persist the failed-attempt counter
        return False
    try:
        account_service.validate_password(new_password, user.email)
    except account_service.AccountError:
        db.rollback()  # un-consume the code so the user can retry with a better password
        raise
    now = datetime.now(timezone.utc)
    user.password_hash = hash_password(new_password)
    user.password_changed_at = now
    user.failed_login_count = 0
    user.locked_until = None
    db.commit()
    email_service.send_security_notice_bg(user.email, "Your password was changed",
                                          "The password on your Forecast account was just changed. All other devices were signed out.")
    return True
