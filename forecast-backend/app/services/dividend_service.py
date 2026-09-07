"""
Dividend payout creation + processing. Creating a payout row (fast, one
row) happens synchronously when an admin finalizes a tournament;
*processing* it (iterating every shareholder and crediting their wallet,
potentially thousands of rows) happens in a background job -- see
app/jobs/tasks.py -- so finalizing a tournament never blocks on that.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.engine.dividend_calculator import compute_dividend_distribution, compute_player_pool
from app.models.dividend import DividendLineItem, DividendPayout, DividendPayoutStatus
from app.models.player import Player, Position
from app.models.tournament import PlacementResult, Tournament, TournamentStatus
from app.services import economic_params_service, wallet_service


def create_payout_for_placement(
    db: Session, tournament: Tournament, placement_result: PlacementResult, max_placement: int
) -> DividendPayout:
    player = db.get(Player, placement_result.player_id)
    # Admin-editable curve (see economic_params_service.py) -- only used
    # as a fallback when the admin hasn't entered an exact prize_won for
    # this placement.
    placement_curve = economic_params_service.get_placement_curve(db)

    # Per the locked-in economy design, Cash Cup / FNCS / Global Championship
    # tournaments pay out of a FIXED synthetic pool ($300k / $1.5M / $3M,
    # admin-tunable -- see economic_params_service.FIXED_POOL_PARAM_BY_TOURNAMENT_TYPE),
    # not a real-world Fortnite prize pool. Other tournament types (MAJOR,
    # OTHER) keep the original behavior of using the admin-entered
    # Tournament.prize_pool. Either way, an exact per-player `prize_won`
    # entered by an admin always takes precedence over both.
    fixed_pool = economic_params_service.get_fixed_tournament_pool(db, tournament.tournament_type)
    effective_prize_pool = fixed_pool if fixed_pool is not None else tournament.prize_pool

    pool = compute_player_pool(
        placement=placement_result.placement,
        prize_won=placement_result.prize_won,
        tournament_prize_pool=effective_prize_pool,
        max_placement=max_placement,
        placement_curve=placement_curve,
    )
    payout = DividendPayout(
        id=uuid.uuid4(),
        tournament_id=tournament.id,
        player_id=player.id,
        total_pool_amount=pool,
        shares_outstanding_snapshot=player.total_shares_outstanding,
        status=DividendPayoutStatus.PENDING,
    )
    db.add(payout)
    db.flush()
    return payout


def process_payout(db: Session, payout_id: uuid.UUID) -> DividendPayout:
    """
    Idempotent: if the payout is already COMPLETED (e.g. the job was
    retried after a crash right after committing), this returns
    immediately without paying anyone twice.

    Record date / "ex-dividend" snapshot: shareholders are whoever holds
    a Position with quantity > 0 *at the moment this function runs* --
    i.e. whenever the background job actually executes, not when the
    tournament result was ingested. For prompt job processing (seconds to
    minutes after finalization) this is a reasonable approximation of
    "who held shares during the tournament"; it is NOT immune to someone
    buying shares in the gap between result ingestion and job processing.
    Locking the snapshot to an explicit record-date field captured at
    finalize_tournament() time (rather than at processing time) is a
    worthwhile follow-up once this matters for real money.
    """
    payout = db.get(DividendPayout, payout_id)
    if payout is None:
        raise ValueError(f"dividend payout {payout_id} not found")
    if payout.status == DividendPayoutStatus.COMPLETED:
        return payout

    payout.status = DividendPayoutStatus.PROCESSING
    db.flush()

    positions = (
        db.query(Position)
        .filter(Position.player_id == payout.player_id, Position.quantity > 0)
        .all()
    )
    holders = [(str(p.user_id), Decimal(p.quantity)) for p in positions]
    positions_by_user = {str(p.user_id): p for p in positions}

    platform_fee_pct = economic_params_service.get_param(db, "dividend.platform_fee_pct")
    per_share_amount, payouts, fee_amount = compute_dividend_distribution(
        pool_amount=payout.total_pool_amount,
        shares_outstanding=Decimal(payout.shares_outstanding_snapshot),
        holders=holders,
        platform_fee_pct=platform_fee_pct,
    )
    payout.per_share_amount = per_share_amount
    payout.platform_fee_amount = fee_amount
    db.flush()

    for user_id_str, amount in payouts:
        if amount <= 0:
            continue
        user_id = uuid.UUID(user_id_str)
        position = positions_by_user[user_id_str]
        ledger_entry = wallet_service.credit_dividend(db, user_id, amount, payout.id)
        db.add(
            DividendLineItem(
                id=uuid.uuid4(),
                payout_id=payout.id,
                user_id=user_id,
                quantity_held_snapshot=position.quantity,
                amount_paid=amount,
                ledger_entry_id=ledger_entry.id,
            )
        )

    payout.status = DividendPayoutStatus.COMPLETED
    payout.completed_at = datetime.now(timezone.utc)
    db.flush()

    _maybe_finalize_tournament(db, payout.tournament_id)
    return payout


def _maybe_finalize_tournament(db: Session, tournament_id: uuid.UUID) -> None:
    remaining = (
        db.query(DividendPayout)
        .filter(DividendPayout.tournament_id == tournament_id, DividendPayout.status != DividendPayoutStatus.COMPLETED)
        .count()
    )
    if remaining == 0:
        tournament = db.get(Tournament, tournament_id)
        tournament.status = TournamentStatus.FINALIZED
        db.flush()
