"""
Player-share IPO auction service -- wires the pure allocation math in
app/engine/auction_calculator.py (read that module's docstring for the
exact-largest-remainder method and the "never overdraw a bidder" money
guarantee) to real wallet holds, share positions, and trade records.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.engine.auction_calculator import BidInput, settle_player_auction
from app.models.auction import AuctionBid, AuctionParticipant, AuctionRound, AuctionRoundStatus
from app.models.order import Trade
from app.models.player import Player, PriceSnapshot
from app.services import economic_params_service, position_service, price_feed, wallet_service
from app.services.exceptions import PlayerNotFoundError, ServiceError
from app.services.house_account import get_or_create_house_user


class AuctionAlreadyOpenError(ServiceError):
    pass


class AuctionNotOpenError(ServiceError):
    pass


class AuctionParticipationRequiredError(ServiceError):
    """Raised when a user tries to bid before joining (paying the entry
    fee for) the round -- see `join_round`."""


class AuctionBidNotFoundError(ServiceError):
    pass


def get_open_round(db: Session) -> AuctionRound | None:
    return db.query(AuctionRound).filter(AuctionRound.status == AuctionRoundStatus.OPEN).one_or_none()


def open_round(db: Session, admin_id: uuid.UUID | None = None) -> AuctionRound:
    """Admin-only: open a new auction round. Only one round may be OPEN
    at a time (finalize the current one before opening another) -- this
    keeps 'which round is a bid against' unambiguous without requiring
    the caller to pass a round id on every request."""
    if get_open_round(db) is not None:
        raise AuctionAlreadyOpenError("an auction round is already open -- finalize it before opening another")
    round_ = AuctionRound(id=uuid.uuid4(), status=AuctionRoundStatus.OPEN, created_by_admin_id=admin_id)
    db.add(round_)
    db.flush()
    return round_


def join_round(db: Session, round_id: uuid.UUID, user_id: uuid.UUID) -> AuctionParticipant:
    """Pay the flat entry fee (economic_params_service key
    'auction.entry_fee') to unlock bidding on every player in this round.
    Idempotent: calling this again after already having joined just
    returns the existing participation record without charging twice."""
    round_ = db.get(AuctionRound, round_id)
    if round_ is None or round_.status != AuctionRoundStatus.OPEN:
        raise AuctionNotOpenError(f"auction round {round_id} is not open")

    existing = (
        db.query(AuctionParticipant)
        .filter(AuctionParticipant.auction_round_id == round_id, AuctionParticipant.user_id == user_id)
        .one_or_none()
    )
    if existing is not None:
        return existing

    entry_fee = economic_params_service.get_param(db, "auction.entry_fee")
    if entry_fee > 0:
        house = get_or_create_house_user(db)
        wallet_service.charge_fee(db, user_id, entry_fee, round_id, memo="Auction entry fee")
        wallet_service.receive_fee_revenue(db, house.id, entry_fee, round_id, memo="Auction entry fee revenue")

    participant = AuctionParticipant(
        id=uuid.uuid4(), auction_round_id=round_id, user_id=user_id, entry_fee_paid=entry_fee
    )
    db.add(participant)
    db.flush()
    return participant


def _require_participant(db: Session, round_id: uuid.UUID, user_id: uuid.UUID) -> None:
    participant = (
        db.query(AuctionParticipant)
        .filter(AuctionParticipant.auction_round_id == round_id, AuctionParticipant.user_id == user_id)
        .one_or_none()
    )
    if participant is None:
        raise AuctionParticipationRequiredError(
            "join this auction round (pay the entry fee) before placing a bid"
        )


def place_bid(db: Session, round_id: uuid.UUID, user_id: uuid.UUID, player_id: uuid.UUID, bid_amount: Decimal) -> AuctionBid:
    """Commit `bid_amount` of cash toward one player in this round. Safe
    to call again for the same (round, user, player) to change the bid
    amount before the round is finalized -- the old hold is released and
    a new one placed for the new amount, same convention as cancelling
    and re-placing a limit order."""
    if bid_amount <= 0:
        raise ValueError("bid_amount must be positive")

    round_ = db.get(AuctionRound, round_id)
    if round_ is None or round_.status != AuctionRoundStatus.OPEN:
        raise AuctionNotOpenError(f"auction round {round_id} is not open")

    _require_participant(db, round_id, user_id)

    player = db.get(Player, player_id)
    if player is None or not player.is_active:
        raise PlayerNotFoundError(str(player_id))

    existing = (
        db.query(AuctionBid)
        .filter(AuctionBid.auction_round_id == round_id, AuctionBid.user_id == user_id, AuctionBid.player_id == player_id)
        .one_or_none()
    )
    if existing is not None:
        wallet_service.release_hold(db, user_id, existing.bid_amount, "auction_bid", existing.id)
        wallet_service.hold_funds(db, user_id, bid_amount, "auction_bid", existing.id)
        existing.bid_amount = bid_amount
        db.flush()
        return existing

    bid_id = uuid.uuid4()
    wallet_service.hold_funds(db, user_id, bid_amount, "auction_bid", bid_id)
    bid = AuctionBid(id=bid_id, auction_round_id=round_id, user_id=user_id, player_id=player_id, bid_amount=bid_amount)
    db.add(bid)
    db.flush()
    return bid


def cancel_bid(db: Session, round_id: uuid.UUID, user_id: uuid.UUID, player_id: uuid.UUID) -> None:
    round_ = db.get(AuctionRound, round_id)
    if round_ is None or round_.status != AuctionRoundStatus.OPEN:
        raise AuctionNotOpenError(f"auction round {round_id} is not open")

    bid = (
        db.query(AuctionBid)
        .filter(AuctionBid.auction_round_id == round_id, AuctionBid.user_id == user_id, AuctionBid.player_id == player_id)
        .one_or_none()
    )
    if bid is None:
        raise AuctionBidNotFoundError(f"no bid on player {player_id} in round {round_id} for this user")

    wallet_service.release_hold(db, user_id, bid.bid_amount, "auction_bid", bid.id)
    db.delete(bid)
    db.flush()


def _settle_player_bids(db: Session, player: Player, bids: list[AuctionBid], house_id: uuid.UUID) -> None:
    house_position = position_service.get_or_create_position(db, house_id, player.id)
    shares_available = house_position.quantity
    total_bids = sum((bid.bid_amount for bid in bids), Decimal("0"))

    if shares_available <= 0 or total_bids <= 0:
        # Nothing to allocate (House already sold out, or -- shouldn't
        # happen given the bid_amount > 0 constraint -- no real demand).
        # Every bidder just gets their full hold back.
        for bid in bids:
            wallet_service.release_hold(db, bid.user_id, bid.bid_amount, "auction_bid", bid.id)
            bid.shares_won = 0
            bid.amount_charged = Decimal("0")
        db.flush()
        return

    bids_by_id = {str(bid.id): bid for bid in bids}
    settlement = settle_player_auction(
        bids=[BidInput(bid_id=str(bid.id), user_id=str(bid.user_id), bid_amount=bid.bid_amount) for bid in bids],
        shares_available=shares_available,
    )

    for allocation in settlement.allocations:
        bid = bids_by_id[allocation.bid_id]

        if allocation.shares_won <= 0:
            wallet_service.release_hold(db, bid.user_id, bid.bid_amount, "auction_bid", bid.id)
            bid.shares_won = 0
            bid.amount_charged = Decimal("0")
            continue

        trade_id = uuid.uuid4()
        db.add(Trade(
            id=trade_id, player_id=player.id, price=settlement.clearing_price, quantity=allocation.shares_won,
            buyer_user_id=bid.user_id, seller_user_id=house_id,
            buy_order_id=None, sell_order_id=None, buyer_is_bot=False, seller_is_bot=True,
        ))
        db.flush()

        # debit_for_trade releases the FULL original hold and debits only
        # the (possibly smaller) amount actually owed in one call -- the
        # same mechanism a limit buy uses when it fills at a better price
        # than its limit (see app/services/wallet_service.py). The engine
        # already guarantees amount_charged <= bid.bid_amount.
        wallet_service.debit_for_trade(
            db, bid.user_id, allocation.amount_charged, trade_id, held_release_amount=bid.bid_amount
        )
        wallet_service.credit_for_trade(db, house_id, allocation.amount_charged, trade_id)
        position_service.transfer_shares_for_trade(
            db, bid.user_id, house_id, player.id, allocation.shares_won, settlement.clearing_price
        )

        db.add(PriceSnapshot(id=uuid.uuid4(), player_id=player.id, price=settlement.clearing_price, volume=allocation.shares_won))
        price_feed.publish_trade(player.id, settlement.clearing_price, allocation.shares_won)

        bid.shares_won = allocation.shares_won
        bid.amount_charged = allocation.amount_charged

    player.ipo_price = settlement.clearing_price
    db.flush()


def finalize_round(db: Session, round_id: uuid.UUID) -> AuctionRound:
    """Admin-only: close bidding and settle every player that received at
    least one bid in this round. Allocates shares out of however many the
    House currently holds for that player (normally 100% of
    `total_shares_outstanding`, since auctions are meant to run right
    after a fresh IPO -- see app/services/player_service.py -- but this
    is computed from the House's actual Position so it's still correct if
    some shares had already changed hands before the auction ran)."""
    round_ = db.get(AuctionRound, round_id)
    if round_ is None or round_.status != AuctionRoundStatus.OPEN:
        raise AuctionNotOpenError(f"auction round {round_id} is not open")

    house = get_or_create_house_user(db)

    all_bids = db.query(AuctionBid).filter(AuctionBid.auction_round_id == round_id).all()
    bids_by_player: dict[uuid.UUID, list[AuctionBid]] = {}
    for bid in all_bids:
        bids_by_player.setdefault(bid.player_id, []).append(bid)

    for player_id, bids in bids_by_player.items():
        player = db.get(Player, player_id)
        if player is None:
            continue
        _settle_player_bids(db, player, bids, house.id)

    round_.status = AuctionRoundStatus.FINALIZED
    round_.finalized_at = datetime.now(timezone.utc)
    db.flush()
    return round_
