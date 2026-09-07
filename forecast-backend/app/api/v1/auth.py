from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
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
from app.services import economic_params_service, password_reset_service, wallet_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
    existing = db.query(User).filter(User.email == payload.email).one_or_none()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = User(
        id=uuid.uuid4(),
        email=payload.email,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name,
        role=UserRole.USER,
        is_active=True,
    )
    db.add(user)
    db.flush()
    wallet_service.get_or_create_wallet(db, user.id)
    # Every new user starts with the same fixed fantasy-cash balance used
    # throughout the validated economy simulation (default $1,000,000,
    # admin-tunable via wallet.starting_balance) -- see
    # app/services/economic_params_service.py. This is the only source of
    # starting capital; /wallet/deposit is admin-only (see app/api/v1/wallet.py)
    # so the simulated economy's total money supply stays meaningful.
    starting_balance = economic_params_service.get_param(db, "wallet.starting_balance")
    if starting_balance > 0:
        wallet_service.deposit(db, user.id, starting_balance, memo="Starting balance")
    db.commit()

    token = create_access_token(user.id)
    return TokenResponse(access_token=token, user_id=user.id)


@router.post("/password-reset/request", response_model=MessageResponse)
def request_password_reset(payload: PasswordResetRequestRequest, db: Session = Depends(get_db)) -> MessageResponse:
    """Always returns the same generic message whether or not the email
    is registered -- see password_reset_service.request_reset's docstring
    for why. If EMAIL_PROVIDER is still the "console" default (see
    app/core/config.py), nothing is actually emailed; the reset link is
    only written to the server log."""
    password_reset_service.request_reset(db, payload.email)
    return MessageResponse(message="If that email is registered, a password reset link has been sent.")


@router.post("/password-reset/confirm", response_model=MessageResponse)
def confirm_password_reset(payload: PasswordResetConfirmRequest, db: Session = Depends(get_db)) -> MessageResponse:
    ok = password_reset_service.confirm_reset(db, payload.token, payload.new_password)
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This reset link is invalid or has expired.")
    return MessageResponse(message="Password updated. You can now log in with your new password.")


@router.get("/me", response_model=UserResponse)
def get_me(user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse(id=user.id, email=user.email, display_name=user.display_name, role=user.role.value)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.query(User).filter(User.email == payload.email).one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")

    token = create_access_token(user.id)
    return TokenResponse(access_token=token, user_id=user.id)
