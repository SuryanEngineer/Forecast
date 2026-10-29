"""Profile & account-settings endpoints (all require login)."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.models.account import UserSession
from app.models.user import User
from app.schemas.account import (
    ChangeEmailRequest,
    ChangePasswordRequest,
    DeleteAccountRequest,
    DisplayNameRequest,
    ProfileResponse,
    SessionRow,
    TagRequest,
)
from app.schemas.auth import CodeRequest, MessageResponse, TokenResponse
from app.services import account_service, auth_code_service, email_service
from app.services.account_service import AccountError

router = APIRouter(prefix="/account", tags=["account"])


def _bad(msg: str, code: int = status.HTTP_400_BAD_REQUEST) -> HTTPException:
    return HTTPException(status_code=code, detail=msg)


def _profile(user: User) -> ProfileResponse:
    return ProfileResponse(
        id=user.id, email=user.email, display_name=user.display_name, tag=user.tag, tag_color=user.tag_color,
        tag_colors=account_service.TAG_COLORS,
        created_at=user.created_at, name_change_available_at=account_service.name_change_available_at(user),
        name_change_cooldown_days=account_service.NAME_CHANGE_COOLDOWN_DAYS, last_login_at=user.last_login_at,
    )


@router.get("/profile", response_model=ProfileResponse)
def get_profile(user: User = Depends(get_current_user)) -> ProfileResponse:
    return _profile(user)


@router.post("/display-name", response_model=ProfileResponse)
def change_display_name(payload: DisplayNameRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ProfileResponse:
    try:
        account_service.change_display_name(db, user, payload.display_name)
    except AccountError as exc:
        db.rollback()
        raise _bad(str(exc))
    db.commit()
    return _profile(user)


@router.post("/tag", response_model=ProfileResponse)
def set_tag(payload: TagRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ProfileResponse:
    try:
        account_service.set_tag(db, user, payload.tag, payload.tag_color)
    except AccountError as exc:
        db.rollback()
        raise _bad(str(exc))
    db.commit()
    return _profile(user)


@router.post("/change-password", response_model=TokenResponse)
def change_password(payload: ChangePasswordRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> TokenResponse:
    """Requires the current password. Signs every other device out and returns a fresh token for this one."""
    if not verify_password(payload.current_password, user.password_hash):
        raise _bad("Current password is incorrect.")
    if payload.current_password == payload.new_password:
        raise _bad("New password must be different from the current one.")
    try:
        account_service.validate_password(payload.new_password, user.email)
    except AccountError as exc:
        raise _bad(str(exc))
    user.password_hash = hash_password(payload.new_password)
    user.password_changed_at = datetime.now(timezone.utc)
    db.commit()
    email_service.send_security_notice(user.email, "Your password was changed",
                                       "The password on your Forecast account was just changed. All other devices were signed out.")
    return TokenResponse(access_token=create_access_token(user.id), user_id=user.id)


@router.post("/email/request-change", response_model=MessageResponse)
def request_email_change(payload: ChangeEmailRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> MessageResponse:
    if not verify_password(payload.password, user.password_hash):
        raise _bad("Password is incorrect.")
    new_email = payload.new_email.strip().lower()
    if new_email == user.email.lower():
        raise _bad("That's already your email.")
    if account_service.email_in_use(db, new_email, exclude_user_id=user.id):
        raise _bad("That email is already in use.")
    try:
        code = auth_code_service.issue_code(db, user.id, "change_email", target_email=new_email)
    except auth_code_service.CodeRateLimited as exc:
        raise _bad(str(exc), status.HTTP_429_TOO_MANY_REQUESTS)
    db.commit()
    email_service.send_change_email_code(new_email, code)
    return MessageResponse(message=f"We sent a code to {new_email}.")


@router.post("/email/confirm-change", response_model=ProfileResponse)
def confirm_email_change(payload: CodeRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ProfileResponse:
    row = auth_code_service.verify_code(db, user.id, "change_email", payload.code)
    if row is None or not row.target_email:
        db.commit()
        raise _bad("That code is invalid or has expired.")
    if account_service.email_in_use(db, row.target_email, exclude_user_id=user.id):
        db.rollback()
        raise _bad("That email is already in use.")
    old = user.email
    user.email = row.target_email
    db.commit()
    email_service.send_security_notice(old, "Your email was changed", f"The email on your Forecast account was changed to {user.email}.")
    return _profile(user)


@router.get("/sessions", response_model=list[SessionRow])
def my_sessions(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[SessionRow]:
    rows = db.query(UserSession).filter(UserSession.user_id == user.id).order_by(UserSession.started_at.desc()).limit(15).all()
    return [
        SessionRow(started_at=r.started_at, last_seen_at=r.last_seen_at, active_minutes=round(r.active_seconds / 60),
                   source=r.source, user_agent=r.user_agent, ip_address=r.ip_address)
        for r in rows
    ]


@router.post("/delete", response_model=MessageResponse)
def delete_account(payload: DeleteAccountRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> MessageResponse:
    if payload.confirm.strip().upper() != "DELETE":
        raise _bad('Type DELETE to confirm.')
    if not verify_password(payload.password, user.password_hash):
        raise _bad("Password is incorrect.")
    email = user.email
    account_service.delete_account(db, user)
    db.commit()
    email_service.send_security_notice(email, "Your account was deleted", "Your Forecast account has been deleted and your personal data removed.")
    return MessageResponse(message="Account deleted.")
