#!/usr/bin/env python3
"""
Remove "Performance Evaluation" tournaments from the roster build (they should never count):
  1. deletes every PlacementResult belonging to a Performance Evaluation tournament,
  2. hides those tournaments (is_historical_archive=True; the tournament rows are kept),
  3. deletes players left with ZERO placements afterwards (cascade removes their mappings/holdings).

Dry run by default. Run this BEFORE sync_pending_tournaments.py --confirm so the roster is rebuilt from
finals only. Real-user exposure is checked first; it refuses if real users hold/traded these players.

    python3 scripts/purge_performance_evals.py
    python3 scripts/purge_performance_evals.py --confirm
"""
from __future__ import annotations

import argparse
import sys

sys.path.insert(0, ".")

from sqlalchemy import func  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.order import Order, Trade  # noqa: E402
from app.models.player import Player, Position  # noqa: E402
from app.models.tournament import PlacementResult, Tournament  # noqa: E402
from scripts.merge_fuzzy_duplicates import _real_user_ids  # noqa: E402

_CHUNK = 1000


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--confirm", action="store_true")
    args = ap.parse_args()

    db = SessionLocal()
    db.expire_on_commit = False
    try:
        pes = db.query(Tournament).filter(func.lower(Tournament.name).like("%performance evaluation%")).all()
        pe_ids = [t.id for t in pes]
        if not pe_ids:
            print("No Performance Evaluation tournaments found.")
            return
        n_place = db.query(func.count(PlacementResult.id)).filter(PlacementResult.tournament_id.in_(pe_ids)).scalar()
        pe_players = {r[0] for r in db.query(PlacementResult.player_id).filter(PlacementResult.tournament_id.in_(pe_ids)).distinct()}
        keep_players = {
            r[0] for r in db.query(PlacementResult.player_id)
            .filter(PlacementResult.tournament_id.notin_(pe_ids)).filter(PlacementResult.player_id.in_(pe_players)).distinct()
        } if pe_players else set()
        orphaned = pe_players - keep_players

        print(f"{len(pes)} Performance Evaluation tournament(s):")
        for t in pes:
            print(f"  - {t.start_time.date() if t.start_time else '?'}  {t.status.value:<16} {t.name}")
        print(f"\nplacements to delete: {n_place}")
        print(f"players appearing in them: {len(pe_players)}   (kept: have other placements = {len(keep_players)}; "
              f"deleted: no placements left = {len(orphaned)})")

        real = _real_user_ids(db)
        exposure = 0
        if real and orphaned:
            ids = list(orphaned)
            exposure += db.query(func.count(Position.id)).filter(Position.quantity > 0, Position.user_id.in_(real), Position.player_id.in_(ids)).scalar()
            exposure += db.query(func.count(Order.id)).filter(Order.user_id.in_(real), Order.player_id.in_(ids)).scalar()
        print(f"real-user exposure on players to be deleted: {exposure}")

        if not args.confirm:
            print("\nDry run only. Re-run with --confirm.")
            return
        if exposure:
            sys.exit("REFUSING: real users hold/ordered these players (cash would not be refunded).")

        db.query(PlacementResult).filter(PlacementResult.tournament_id.in_(pe_ids)).delete(synchronize_session=False)
        for t in pes:
            t.is_historical_archive = True
        db.commit()
        print("Placements deleted; tournaments hidden.")

        ids = list(orphaned)
        for i in range(0, len(ids), _CHUNK):
            db.query(Player).filter(Player.id.in_(ids[i:i + _CHUNK])).delete(synchronize_session=False)
            db.commit()
        print(f"Deleted {len(ids)} player(s) with no remaining placements.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
