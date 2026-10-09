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
from decimal import ROUND_DOWN, Decimal

from sqlalchemy.orm import Session

from app.engine.dividend_calculator import compute_dividend_distribution, compute_player_pool
from app.models.dividend import DividendLineItem, DividendPayout, DividendPayoutStatus
from app.models.player import Player
from app.models.tournament import PlacementResult, Tournament, TournamentStatus
from app.services import economic_params_service, position_service, wallet_service


class PoolContext:
    """Everything needed to price a placement's dividend pool for one tournament, loaded once (so
    previewing a 100-team leaderboard doesn't re-query the economy parameters per row)."""

    def __init__(self, db: Session, tournament: Tournament) -> None:
        self.placement_curve = economic_params_service.get_placement_curve(db)
        fixed_pool = economic_params_service.get_fixed_tournament_pool(db, tournament.tournament_type)
        if fixed_pool is not None:
            fixed_pool = fixed_pool * economic_params_service.get_region_multiplier(db, tournament.region)
        self.effective_prize_pool = fixed_pool if fixed_pool is not None else tournament.prize_pool
        self.platform_fee_pct = economic_params_service.get_param(db, "dividend.platform_fee_pct")

    def pool_for(self, placement_result: PlacementResult, max_placement: int) -> Decimal:
        return compute_player_pool(
            placement=placement_result.placement,
            prize_won=placement_result.prize_won,
            tournament_prize_pool=self.effective_prize_pool,
            max_placement=max_placement,
            placement_curve=self.placement_curve,
        )

    def per_share_for(self, pool: Decimal, shares_outstanding: int) -> Decimal | None:
        """Per-share dividend a pool works out to (after the platform fee), same maths as process_payout."""
        if shares_outstanding <= 0 or pool <= 0:
            return None
        fee = (pool * self.platform_fee_pct).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        return (pool - fee) / Decimal(shares_outstanding)


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
    if fixed_pool is not None:
        # Region scale factor: an EU/NAC Cash Cup pays the full fixed pool;
        # a smaller region's Cash Cup pays a scaled-down amount of that same
        # pool (see economic_params_service.DEFAULT_REGION_MULTIPLIERS).
        # Only applies to the fixed synthetic pools -- an admin-entered
        # prize_pool (MAJOR/OTHER types) is already a real, region-specific
        # number and isn't rescaled.
        region_multiplier = economic_params_service.get_region_multiplier(db, tournament.region)
        fixed_pool = fixed_pool * region_multiplier
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

    Record date / "ex-dividend" snapshot: shareholders are whoever held
    shares at the tournament's START TIME (Tournament.start_time), and each
    is paid in proportion to what they held then -- reconstructed from the
    timestamped ShareTransfer ledger, so it doesn't matter when this job
    runs. Buying a player after the tournament has started earns nothing
    from it; selling after it started still earns the dividend.
    """
    payout = db.get(DividendPayout, payout_id)
    if payout is None:
        raise ValueError(f"dividend payout {payout_id} not found")
    if payout.status == DividendPayoutStatus.COMPLETED:
        return payout

    payout.status = DividendPayoutStatus.PROCESSING
    db.flush()

    # Record date = the tournament's START. Whoever held shares at that instant is paid (in proportion to
    # what they held then); shares bought afterwards earn nothing from this tournament and shares sold
    # afterwards still do. Reconstructed from the timestamped ShareTransfer ledger (see
    # position_service.holdings_at). No start time on file -> fall back to "now" (the old behavior).
    tournament = db.get(Tournament, payout.tournament_id)
    record_date = tournament.start_time if tournament is not None and tournament.start_time is not None else datetime.now(timezone.utc)
    held_at_start = position_service.holdings_at(db, payout.player_id, record_date)
    holders = [(str(uid), Decimal(qty)) for uid, qty in held_at_start.items()]
    # Their ledger-backed quantity, for the DividendLineItem snapshot below.
    qty_by_user = {str(uid): qty for uid, qty in held_at_start.items()}

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
        ledger_entry = wallet_service.credit_dividend(db, user_id, amount, payout.id)
        db.add(
            DividendLineItem(
                id=uuid.uuid4(),
                payout_id=payout.id,
                user_id=user_id,
                quantity_held_snapshot=qty_by_user[user_id_str],
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
