"""
User-facing auction endpoints: join the currently open round (pays the
flat entry fee), place/change/cancel a bid on a player, and check your
own bids. Opening and finalizing a round are admin-only actions -- see
app/api/v1/admin.py.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.auction import AuctionBid
from app.models.user import User
from app.schemas.auction import AuctionBidRequest, AuctionBidResponse, AuctionParticipantResponse, AuctionRoundResponse
from app.services import auction_service
from app.services.exceptions import ServiceError

router = APIRouter(prefix="/auctions", tags=["auctions"])


def _to_http_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/current", response_model=AuctionRoundResponse | None)
def get_current_round(db: Session = Depends(get_db)) -> AuctionRoundResponse | None:
    """The currently OPEN auction round, if any. Returns null if no round
    is open right now."""
    round_ = auction_service.get_open_round(db)
    db.commit()
    return round_


@router.post("/{round_id}/join", response_model=AuctionParticipantResponse, status_code=status.HTTP_201_CREATED)
def join_round(round_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> AuctionParticipantResponse:
    """Pay the flat entry fee to unlock bidding on every player in this
    round. Safe to call again -- already having joined just returns your
    existing participation record, you're not charged twice."""
    try:
        participant = auction_service.join_round(db, round_id, user.id)
        db.commit()
    except ServiceError as exc:
        db.rollback()
        raise _to_http_error(exc)
    return participant


@router.post("/{round_id}/bids", response_model=AuctionBidResponse, status_code=status.HTTP_201_CREATED)
def place_bid(
    round_id: uuid.UUID, payload: AuctionBidRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> AuctionBidResponse:
    """Commit cash toward one player in this round. You must have joined
    the round first (see /join). Calling this again for a player you've
    already bid on replaces your previous bid amount for that player."""
    try:
        bid = auction_service.place_bid(db, round_id, user.id, payload.player_id, payload.bid_amount)
        db.commit()
    except ServiceError as exc:
        db.rollback()
        raise _to_http_error(exc)
    except ValueError as exc:
        db.rollback()
        raise _to_http_error(exc)
    return bid


@router.delete("/{round_id}/bids/{player_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def cancel_bid(
    round_id: uuid.UUID, player_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> None:
    """Withdraw your bid on a player and release the held cash, while the
    round is still open."""
    try:
        auction_service.cancel_bid(db, round_id, user.id, player_id)
        db.commit()
    except ServiceError as exc:
        db.rollback()
        raise _to_http_error(exc)


@router.get("/{round_id}/bids/me", response_model=list[AuctionBidResponse])
def get_my_bids(round_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[AuctionBidResponse]:
    bids = db.query(AuctionBid).filter(AuctionBid.auction_round_id == round_id, AuctionBid.user_id == user.id).all()
    db.commit()
    return bids
