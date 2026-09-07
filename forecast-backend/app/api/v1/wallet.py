from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.wallet import LedgerEntry
from app.schemas.wallet import DepositRequest, LedgerEntryResponse, WalletResponse, WithdrawRequest
from app.services import wallet_service
from app.services.exceptions import ServiceError

router = APIRouter(prefix="/wallet", tags=["wallet"])


@router.get("/me", response_model=WalletResponse)
def get_my_wallet(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> WalletResponse:
    wallet = wallet_service.get_or_create_wallet(db, user.id)
    db.commit()
    return WalletResponse(
        id=wallet.id, user_id=wallet.user_id, cash_balance=wallet.cash_balance,
        held_balance=wallet.held_balance, available_balance=wallet.available_balance,
    )


@router.post("/deposit", response_model=WalletResponse)
def deposit(payload: DepositRequest, admin: User = Depends(get_current_admin), db: Session = Depends(get_db)) -> WalletResponse:
    """Admin-only cash grant (see DepositRequest docstring for why this
    isn't self-serve anymore). Every user already receives a fixed
    starting balance automatically at registration -- this endpoint is
    for admin top-ups/corrections only, e.g. while testing."""
    target_user_id = payload.user_id or admin.id
    try:
        wallet = wallet_service.deposit(db, target_user_id, payload.amount, memo=payload.memo)
        db.commit()
    except ServiceError as exc:
        db.rollback()
        raise _to_http_error(exc)
    return WalletResponse(
        id=wallet.id, user_id=wallet.user_id, cash_balance=wallet.cash_balance,
        held_balance=wallet.held_balance, available_balance=wallet.available_balance,
    )


@router.post("/withdraw", response_model=WalletResponse)
def withdraw(payload: WithdrawRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> WalletResponse:
    try:
        wallet = wallet_service.withdraw(db, user.id, payload.amount, memo=payload.memo)
        db.commit()
    except ServiceError as exc:
        db.rollback()
        raise _to_http_error(exc)
    return WalletResponse(
        id=wallet.id, user_id=wallet.user_id, cash_balance=wallet.cash_balance,
        held_balance=wallet.held_balance, available_balance=wallet.available_balance,
    )


@router.get("/ledger", response_model=list[LedgerEntryResponse])
def get_my_ledger(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[LedgerEntryResponse]:
    wallet = wallet_service.get_or_create_wallet(db, user.id)
    entries = (
        db.query(LedgerEntry)
        .filter(LedgerEntry.wallet_id == wallet.id)
        .order_by(LedgerEntry.created_at.desc())
        .limit(200)
        .all()
    )
    db.commit()
    return entries


def _to_http_error(exc: ServiceError):
    from fastapi import HTTPException, status
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
