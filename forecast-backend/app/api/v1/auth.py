from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.models.user import User, UserRole
from app.schemas.auth import (
    LoginRequest,
    MessageResponse,
    PasswordResetConfirmRequest,
    PasswordResetRequestRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.services import (
    account_service,
    economic_params_service,
    password_reset_service,
    session_service,
    wallet_service,
)
from app.services.account_service import AccountError

router = APIRouter(prefix="/auth", tags=["auth"])

# Same error for "no such email" and "wrong password" so the endpoint can't be used to discover accounts.
_BAD_LOGIN = "Invalid email or password"


def _client(request: Request) -> tuple[str | None, str | None]:
    fwd = request.headers.get("x-forwarded-for")
    ip = fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else None)
    return ip, request.headers.get("user-agent")


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id, email=user.email, display_name=user.display_name, role=user.role.value, tag=user.tag,
        tag_color=user.tag_color, created_at=user.created_at,
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    email = payload.email.strip().lower()
    if not payload.accept_terms:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You must accept the Terms of Service and Privacy Policy.")
    if account_service.email_in_use(db, email):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
    try:
        account_service.validate_password(payload.password, email)
        display_name = account_service.validate_display_name(db, payload.display_name)
    except AccountError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    now = datetime.now(timezone.utc)
    user = User(
        id=uuid.uuid4(), email=email, password_hash=hash_password(payload.password), display_name=display_name,
        role=UserRole.USER, is_active=True, terms_accepted_at=now, last_login_at=now, login_count=1,
        password_changed_at=None,
    )
    db.add(user)
    db.flush()
    wallet_service.get_or_create_wallet(db, user.id)
    # Every new user starts with the same fixed fantasy-cash balance (admin-tunable via wallet.starting_balance).
    # /wallet/deposit is admin-only so the economy's money supply stays meaningful.
    starting_balance = economic_params_service.get_param(db, "wallet.starting_balance")
    if starting_balance > 0:
        wallet_service.deposit(db, user.id, starting_balance, memo="Starting balance")
    ip, ua = _client(request)
    session_service.start_session(db, user, "register", ip, ua)
    db.commit()
    return TokenResponse(access_token=create_access_token(user.id), user_id=user.id)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    email = payload.email.strip().lower()
    user = db.query(User).filter(func.lower(User.email) == email).first()
    now = datetime.now(timezone.utc)

    if user is not None and user.locked_until is not None and _aware(user.locked_until) > now:
        mins = max(1, int((_aware(user.locked_until) - now).total_seconds() // 60) + 1)
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            detail=f"Too many failed attempts. Try again in {mins} minute(s) or reset your password.")

    if user is None or not verify_password(payload.password, user.password_hash):
        if user is not None:
            user.failed_login_count += 1
            if user.failed_login_count >= settings.LOGIN_MAX_FAILED_ATTEMPTS:
                user.locked_until = now + timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)
                user.failed_login_count = 0
            db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_BAD_LOGIN)
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    user.login_count = (user.login_count or 0) + 1
    ip, ua = _client(request)
    session_service.start_session(db, user, "login", ip, ua)
    db.commit()
    return TokenResponse(access_token=create_access_token(user.id), user_id=user.id)


@router.get("/me", response_model=UserResponse)
def get_me(user: User = Depends(get_current_user)) -> UserResponse:
    return user_response(user)


@router.post("/heartbeat", response_model=MessageResponse)
def heartbeat(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> MessageResponse:
    """Called by the frontend about once a minute while the tab is visible -- feeds session / time-on-site analytics."""
    ip, ua = _client(request)
    session_service.heartbeat(db, user, ip, ua)
    db.commit()
    return MessageResponse(message="ok")


# ---- Forgot password (emailed 6-digit code) ----------------------------------------------------------------------

@router.post("/password-reset/request", response_model=MessageResponse)
def request_password_reset(payload: PasswordResetRequestRequest, db: Session = Depends(get_db)) -> MessageResponse:
    """Always returns the same message whether or not the email is registered (no account-discovery oracle)."""
    password_reset_service.request_reset(db, payload.email.strip().lower())
    return MessageResponse(message="If that email is registered, a 6-digit code has been sent. It expires in "
                                   f"{settings.EMAIL_CODE_EXPIRE_MINUTES} minutes.")


@router.post("/password-reset/confirm", response_model=MessageResponse)
def confirm_password_reset(payload: PasswordResetConfirmRequest, db: Session = Depends(get_db)) -> MessageResponse:
    try:
        ok = password_reset_service.confirm_reset(db, payload.email.strip().lower(), payload.code, payload.new_password)
    except AccountError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="That code is invalid or has expired.")
    return MessageResponse(message="Password updated. You can now log in with your new password.")
