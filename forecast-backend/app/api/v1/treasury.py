from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.treasury import TreasuryHolding
from app.models.user import User
from app.schemas.treasury import TreasuryHoldingResponse, TreasuryInstrumentResponse, TreasuryPurchaseRequest
from app.services import treasury_service
from app.services.exceptions import ServiceError

router = APIRouter(prefix="/treasury", tags=["treasury"])


@router.get("/instrument", response_model=TreasuryInstrumentResponse)
def get_active_instrument(db: Session = Depends(get_db)) -> TreasuryInstrumentResponse:
    instrument = treasury_service.get_or_create_active_instrument(db)
    db.commit()
    return instrument


@router.post("/purchase", response_model=TreasuryHoldingResponse, status_code=status.HTTP_201_CREATED)
def purchase(payload: TreasuryPurchaseRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> TreasuryHoldingResponse:
    try:
        holding = treasury_service.purchase(db, user.id, payload.amount)
        db.commit()
    except ServiceError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return holding


@router.post("/{holding_id}/redeem", response_model=TreasuryHoldingResponse)
def redeem(holding_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> TreasuryHoldingResponse:
    try:
        holding = treasury_service.redeem(db, user.id, holding_id)
        db.commit()
    except ServiceError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return holding


@router.get("/me", response_model=list[TreasuryHoldingResponse])
def list_my_holdings(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[TreasuryHoldingResponse]:
    return (
        db.query(TreasuryHolding)
        .filter(TreasuryHolding.user_id == user.id)
        .order_by(TreasuryHolding.purchased_at.desc())
        .all()
    )
