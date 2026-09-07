from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.dividend import DividendLineItem, DividendPayout
from app.models.user import User
from app.schemas.dividend import DividendLineItemResponse, DividendPayoutResponse

router = APIRouter(prefix="/dividends", tags=["dividends"])


@router.get("/player/{player_id}", response_model=list[DividendPayoutResponse])
def get_payouts_for_player(player_id: uuid.UUID, db: Session = Depends(get_db)) -> list[DividendPayoutResponse]:
    return (
        db.query(DividendPayout)
        .filter(DividendPayout.player_id == player_id)
        .order_by(DividendPayout.created_at.desc())
        .all()
    )


@router.get("/me", response_model=list[DividendLineItemResponse])
def get_my_dividend_history(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[DividendLineItemResponse]:
    return (
        db.query(DividendLineItem)
        .filter(DividendLineItem.user_id == user.id)
        .order_by(DividendLineItem.created_at.desc())
        .limit(200)
        .all()
    )
