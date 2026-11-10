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

from app.engine import payout_policy, performance_eval
from app.engine.dividend_calculator import compute_dividend_distribution, compute_player_pool
from app.models.dividend import DividendLineItem, DividendPayout, DividendPayoutStatus
from app.models.player import Player
from app.models.tournament import PlacementResult, Tournament, TournamentStatus, TournamentType
from app.services import economic_params_service, position_service, wallet_service


def _parse_iso(value) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def tournament_finished_at(db: Session, tournament: Tournament) -> datetime:
    """When the tournament ACTUALLY finished, for dating its dividends: the end time of the last game anyone played in it
    (from the per-game `sessionHistory` stored on the results), because the Osirion window a cup is tracked under can stay
    open long after the last game. Falls back to the tournament's own end time, then to now. Never in the future.
    (The per-game JSON is only scanned for small fields -- a few hundred result rows -- to keep this cheap.)"""
    now = datetime.now(timezone.utc)
    last_game: datetime | None = None
    n = db.query(PlacementResult.id).filter(PlacementResult.tournament_id == tournament.id).limit(401).count()
    if 0 < n <= 400:
        for (raw,) in db.query(PlacementResult.raw_stats).filter(PlacementResult.tournament_id == tournament.id).all():
            for session in (raw or {}).get("sessionHistory") or []:
                ended = _parse_iso(session.get("endTime"))
                if ended is not None and (last_game is None or ended > last_game):
                    last_game = ended
    if last_game is not None and last_game <= now:
        return last_game
    if tournament.end_time is not None:
        end = tournament.end_time if tournament.end_time.tzinfo else tournament.end_time.replace(tzinfo=timezone.utc)
        if end <= now:
            return end
    return now


class PoolContext:
    """Everything needed to price a placement's dividend pool for one tournament, loaded once (so
    previewing a 100-team leaderboard doesn't re-query the economy parameters per row)."""

    def __init__(self, db: Session, tournament: Tournament) -> None:
        # The global curve, or its top-N version for an event that pays only its top places (see engine/payout_policy.py).
        self.placement_curve = payout_policy.curve_for_rules(economic_params_service.get_placement_curve(db), tournament.name, tournament.format_rules)
        self.paid_places = payout_policy.paid_places_for(tournament.name, tournament.format_rules)
        rules = tournament.format_rules or {}
        fixed_pool = economic_params_service.get_tournament_pool(db, tournament.tournament_type, tournament.region, rules)
        self.effective_prize_pool = fixed_pool if fixed_pool is not None else tournament.prize_pool
        self.platform_fee_pct = economic_params_service.get_param(db, "dividend.platform_fee_pct")
        # Performance Evaluation cups -- and any event whose scoring rewards only game wins -- pay per game WON, not per
        # placement. A PE cup uses its own pool (no region scaling); another win-scored event splits ITS pool the same way.
        self.is_performance_eval = tournament.tournament_type == TournamentType.PERFORMANCE_EVAL or rules.get("scoring") == "wins"
        if self.is_performance_eval:
            if tournament.tournament_type == TournamentType.PERFORMANCE_EVAL:
                self.eval_pool = economic_params_service.get_param(db, "dividend.performance_eval_pool")
            else:
                self.eval_pool = self.effective_prize_pool or Decimal("0")
            self.eval_win_share = economic_params_service.get_param(db, "dividend.performance_eval_win_share")

    def pool_for(self, placement_result: PlacementResult, max_placement: int) -> Decimal:
        if self.is_performance_eval:
            return performance_eval.player_pool(placement_result.raw_stats, self.eval_pool, self.eval_win_share)
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
    db: Session, tournament: Tournament, placement_result: PlacementResult, max_placement: int, ctx: "PoolContext | None" = None
) -> DividendPayout:
    player = db.get(Player, placement_result.player_id)
    # One shared way to price a placement (also used by every preview and valuation): the fixed synthetic pool for the
    # tier ($150k qualifier / $300k Cash Cup / $1.5M FNCS / $3M Global, admin-tunable -- see
    # economic_params_service.FIXED_POOL_PARAM_BY_TOURNAMENT_TYPE) scaled by region, split by the placement curve (top-N
    # events such as the Arenas Cash Cup pay only their top places), or per game won for a Performance Evaluation cup.
    # An exact per-player `prize_won` entered by an admin always takes precedence.
    pool = (ctx or PoolContext(db, tournament)).pool_for(placement_result, max_placement)
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

    # The money is dated to when the tournament FINISHED, not to when this job happened to run (a retroactive or delayed
    # payout would otherwise show up as a jump today). Falls back to now when there is no end time or it is in the future.
    paid_at = tournament_finished_at(db, tournament) if tournament is not None else datetime.now(timezone.utc)

    for user_id_str, amount in payouts:
        if amount <= 0:
            continue
        user_id = uuid.UUID(user_id_str)
        ledger_entry = wallet_service.credit_dividend(db, user_id, amount, payout.id, occurred_at=paid_at)
        db.add(
            DividendLineItem(
                id=uuid.uuid4(),
                payout_id=payout.id,
                user_id=user_id,
                quantity_held_snapshot=qty_by_user[user_id_str],
                amount_paid=amount,
                ledger_entry_id=ledger_entry.id,
                created_at=paid_at,
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
        try:
            from app.services import notification_service  # local import: keeps this module import-light

            notification_service.dividends_paid(db, tournament_id)
        except Exception:  # noqa: BLE001 -- a notification must never block a payout
            import logging

            logging.getLogger(__name__).exception("dividend notifications failed for tournament %s", tournament_id)
