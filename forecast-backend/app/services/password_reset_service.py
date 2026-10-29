"""
Forgot-password flow with emailed 6-digit codes (see auth_code_service for the code security properties).

`request_reset` always appears to succeed whether or not the email has an account (no account-discovery oracle).
`confirm_reset` checks the code, sets the new password, clears any login lockout and invalidates every previously issued login token.

(The older link/token flow -- PasswordResetToken -- is retired; its table is kept so old rows don't need a migration.)
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.user import User
from app.services import account_service, auth_code_service, email_service

PURPOSE = "password_reset"


def request_reset(db: Session, email: str) -> None:
    user = db.query(User).filter(func.lower(User.email) == email.lower()).first()
    if user is None or not user.is_active:
        return
    try:
        code = auth_code_service.issue_code(db, user.id, PURPOSE)
    except auth_code_service.CodeRateLimited:
        return  # silently: same response either way
    db.commit()
    email_service.send_password_reset_code(user.email, code)


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
    email_service.send_security_notice(user.email, "Your password was changed",
                                       "The password on your Forecast account was just changed. All other devices were signed out.")
    return True
