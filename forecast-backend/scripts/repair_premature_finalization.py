#!/usr/bin/env python3
"""
Repair a tournament that was finalized (and paid) BEFORE its last game had a winner.

Two steps, run one after the other:

  1. REOPEN   python scripts/repair_premature_finalization.py --id <tournament id> --reopen --confirm
     Puts the tournament back to "results pending" and forgets its stored progress. Nothing is paid or taken back. The live sync
     (every ~45 s) then re-pulls the full results and finishes it with the corrected rule: the last game must have a winner and the
     lobby must stay quiet for 30 minutes. Players with no payout yet (e.g. the winner of the missed game) are paid normally by
     that finalization; players who already have a payout are skipped by it.
     Wait until the tournament shows as completed again (or `live_progress.over` is true).

  2. TOP UP   python scripts/repair_premature_finalization.py --id <tournament id> --topup            # dry run
              python scripts/repair_premature_finalization.py --id <tournament id> --topup --confirm
     For every player who ALREADY had a payout, re-prices the pool from the refreshed results (a Performance Evaluation cup pays per
     game won) and pays shareholders ONLY the difference: each holder at the start gets (new amount - what they were paid), credited
     to their wallet as a normal dated dividend credit, and the payout / line item totals are raised to match. Nothing is ever taken
     back: if a pool would go DOWN it is left alone and reported.

Back up (or be sure about) the database first: step 2 moves money.
"""
from __future__ import annotations

import argparse
import sys
import time
import uuid
from collections import defaultdict
from decimal import Decimal

sys.path.insert(0, ".")

from sqlalchemy.exc import OperationalError  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.engine.dividend_calculator import compute_dividend_distribution  # noqa: E402
from app.models.dividend import DividendLineItem, DividendPayout  # noqa: E402
from app.models.player import Player  # noqa: E402
from app.models.tournament import PlacementResult, Tournament, TournamentStatus  # noqa: E402
from app.services import dividend_service, economic_params_service, position_service, wallet_service  # noqa: E402

ZERO = Decimal("0")


def _usd(x) -> str:
    return f"${Decimal(str(x)):,.2f}"


def _load(db, tid: str) -> Tournament:
    t = db.get(Tournament, uuid.UUID(tid))
    if t is None:
        sys.exit(f"No tournament with id {tid}")
    return t


def reopen(args) -> None:
    db = SessionLocal()
    try:
        t = _load(db, args.id)
        progress = (t.format_rules or {}).get("progress") or {}
        print(f"{t.name}  [{t.status.value}]  stored progress: games done {progress.get('games_done')}, over={progress.get('over')}")
        if t.status != TournamentStatus.FINALIZED:
            print("It is not finalized, so there is nothing to reopen.")
            return
        n_pay = db.query(DividendPayout).filter(DividendPayout.tournament_id == t.id).count()
        print(f"It has {n_pay} payouts already paid; they are kept (reopening pays and takes back nothing).")
        if not args.confirm:
            print("\nDry run only. Re-run with --confirm to reopen it.")
            return
        rules = dict(t.format_rules or {})
        rules.pop("progress", None)
        t.format_rules = rules
        t.status = TournamentStatus.RESULTS_PENDING
        db.commit()
        print("\nReopened. The live sync will re-pull the results within a minute or so and finish it under the corrected rule.")
        print("Check the tournament (or /api/v1/tournaments/<id>): when it is completed again, run step 2 (--topup).")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def topup(args, verbose: bool) -> None:
    say = print if verbose else (lambda *a, **k: None)
    db = SessionLocal()
    try:
        t = _load(db, args.id)
        progress = (t.format_rules or {}).get("progress") or {}
        say(f"{t.name}  [{t.status.value}]  progress: games done {progress.get('games_done')}, over={progress.get('over')}")
        if t.status != TournamentStatus.FINALIZED or progress.get("over") is not True:
            sys.exit("Not ready: the tournament must be completed again with progress.over = true (run --reopen and wait first).")

        results = db.query(PlacementResult).filter(PlacementResult.tournament_id == t.id).all()
        max_placement = len(results)
        ctx = dividend_service.PoolContext(db, t)
        payouts = {p.player_id: p for p in db.query(DividendPayout).filter(DividendPayout.tournament_id == t.id).all()}
        record_date = t.start_time
        paid_at = dividend_service.tournament_finished_at(db, t)
        fee_pct = economic_params_service.get_param(db, "dividend.platform_fee_pct")

        plan = []   # (payout, player, new_pool, per_share, fee, {user_id: delta}, {user_id: new_amount})
        skipped_lower = []
        for res in results:
            payout = payouts.get(res.player_id)
            if payout is None:
                continue                      # a player with no payout yet is paid by the normal finalization
            new_pool = ctx.pool_for(res, max_placement)
            old_pool = Decimal(str(payout.total_pool_amount))
            if new_pool == old_pool:
                continue
            player = db.get(Player, res.player_id)
            if new_pool < old_pool:
                skipped_lower.append((player.gamertag, old_pool, new_pool))
                continue
            held = position_service.holdings_at(db, payout.player_id, record_date) if record_date else {}
            holders = [(str(uid), Decimal(q)) for uid, q in held.items()]
            per_share, amounts, fee = compute_dividend_distribution(
                pool_amount=new_pool, shares_outstanding=Decimal(payout.shares_outstanding_snapshot), holders=holders, platform_fee_pct=fee_pct,
            )
            old_by_user = {str(li.user_id): Decimal(str(li.amount_paid)) for li in db.query(DividendLineItem).filter(DividendLineItem.payout_id == payout.id).all()}
            deltas = {}
            for uid, amount in amounts:
                d = amount - old_by_user.get(uid, ZERO)
                if d > 0:
                    deltas[uid] = d
            plan.append((payout, player, new_pool, per_share, fee, deltas, dict(amounts), held))

        say(f"\nPlayers whose pool goes up: {len(plan)}")
        total = ZERO
        for payout, player, new_pool, _ps, _fee, deltas, _amts, _held in plan:
            extra = sum(deltas.values(), ZERO)
            total += extra
            say(f"  - {player.gamertag}: pool {_usd(payout.total_pool_amount)} -> {_usd(new_pool)}  (pays {len(deltas)} holder(s) {_usd(extra)} more)")
        say(f"  total extra to pay: {_usd(total)}")
        for tag, old, new in skipped_lower:
            say(f"  NOT changed (pool would drop, nothing is ever taken back): {tag} {_usd(old)} -> {_usd(new)}")

        if not plan:
            say("\nNothing to top up.")
            return
        if not args.confirm:
            say("\nDry run only. Re-run with --confirm to pay the differences.")
            return

        # Same wallet order every time (users sorted), so a concurrent trade can queue behind us instead of deadlocking.
        all_users = sorted({uid for p in plan for uid in p[5]})
        by_user = defaultdict(list)
        for payout, player, new_pool, per_share, fee, deltas, amounts, held in plan:
            for uid, d in deltas.items():
                by_user[uid].append((payout, d, amounts[uid], held))
        for uid in all_users:
            for payout, delta, new_amount, held in by_user[uid]:
                wallet_service.credit_dividend(db, uuid.UUID(uid), delta, payout.id, occurred_at=paid_at)
                li = (
                    db.query(DividendLineItem)
                    .filter(DividendLineItem.payout_id == payout.id, DividendLineItem.user_id == uuid.UUID(uid))
                    .one_or_none()
                )
                if li is not None:
                    li.amount_paid = Decimal(str(li.amount_paid)) + delta
                else:
                    db.add(DividendLineItem(
                        id=uuid.uuid4(), payout_id=payout.id, user_id=uuid.UUID(uid), quantity_held_snapshot=held.get(uuid.UUID(uid), 0),
                        amount_paid=delta, ledger_entry_id=None, created_at=paid_at,
                    ))
        for payout, _player, new_pool, per_share, fee, _d, _a, _h in plan:
            payout.total_pool_amount = new_pool
            payout.per_share_amount = per_share
            payout.platform_fee_amount = fee
        db.commit()
        print(f"\nDone: paid {_usd(total)} more across {len(all_users)} user(s) for {len(plan)} player(s).")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--id", required=True, help="tournament id")
    ap.add_argument("--reopen", action="store_true", help="step 1: put it back to results-pending")
    ap.add_argument("--topup", action="store_true", help="step 2: pay the differences for players who were already paid")
    ap.add_argument("--confirm", action="store_true")
    args = ap.parse_args()
    if args.reopen == args.topup:
        sys.exit("Choose exactly one of --reopen or --topup.")
    if args.reopen:
        reopen(args)
        return
    for attempt in range(1, 6):
        try:
            topup(args, verbose=(attempt == 1))
            return
        except OperationalError as exc:
            if "deadlock" not in str(exc).lower() or attempt == 5:
                raise
            print(f"\n(database deadlock with a live job -- nothing was changed; retrying, attempt {attempt + 1})")
            time.sleep(2 * attempt)


if __name__ == "__main__":
    main()
