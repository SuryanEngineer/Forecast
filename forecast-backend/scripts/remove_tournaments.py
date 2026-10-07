#!/usr/bin/env python3
"""
Remove tournaments (matched by name text) and everything hanging off them, then delete any players left with NO
placements. Use it to undo tournaments that should never have been tracked (e.g. a half-synced PlayStation cup).

Deleted via DB cascade: the Tournament row, its Osirion mapping, its raw-result archive and its placements.
Players with zero placements afterwards are deleted too (they only existed because of the removed tournament).
Refuses if a real (non-bot, non-House) user holds/ordered one of those players.

Dry run by default.

    python3 scripts/remove_tournaments.py --grep PlayStation
    python3 scripts/remove_tournaments.py --grep PlayStation --confirm
    python3 scripts/remove_tournaments.py --grep "PlayStation" --grep "Console" --confirm
"""
from __future__ import annotations

import argparse
import sys

sys.path.insert(0, ".")

from sqlalchemy import func, or_  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.order import Order  # noqa: E402
from app.models.player import Player, Position  # noqa: E402
from app.models.tournament import PlacementResult, Tournament  # noqa: E402
from scripts.merge_fuzzy_duplicates import _real_user_ids  # noqa: E402

_CHUNK = 1000


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--grep", action="append", required=True, help="Tournament name contains this (repeatable, OR).")
    ap.add_argument("--confirm", action="store_true")
    args = ap.parse_args()

    db = SessionLocal()
    db.expire_on_commit = False
    try:
        conds = [func.lower(Tournament.name).like(f"%{g.lower()}%") for g in args.grep]
        tournaments = db.query(Tournament).filter(or_(*conds)).order_by(Tournament.start_time.asc().nullslast()).all()
        if not tournaments:
            print("No matching tournaments.")
            return
        ids = [t.id for t in tournaments]
        counts = dict(db.query(PlacementResult.tournament_id, func.count(PlacementResult.id))
                      .filter(PlacementResult.tournament_id.in_(ids)).group_by(PlacementResult.tournament_id).all())
        print(f"{len(tournaments)} tournament(s) match:")
        for t in tournaments:
            print(f"  {str(t.start_time.date()) if t.start_time else '?':<11} {t.status.value:<16} "
                  f"{counts.get(t.id, 0):>5} placements  {t.name}")

        affected = {r[0] for r in db.query(PlacementResult.player_id).filter(PlacementResult.tournament_id.in_(ids)).distinct()}
        kept = {r[0] for r in db.query(PlacementResult.player_id)
                .filter(PlacementResult.tournament_id.notin_(ids)).filter(PlacementResult.player_id.in_(affected)).distinct()} if affected else set()
        orphans = list(affected - kept)
        # players created by an interrupted sync can exist with no placement row at all -- sweep those up too
        no_placement = [r[0] for r in db.query(Player.id).filter(~Player.id.in_(db.query(PlacementResult.player_id))).all()]
        orphans = list(set(orphans) | set(no_placement))
        print(f"\nplayers in these tournaments: {len(affected)}   (also on other tournaments, kept: {len(kept)})")
        print(f"players that would be deleted (no placements left / never had any): {len(orphans)}")

        real = _real_user_ids(db)
        exposure = 0
        if real and orphans:
            exposure += db.query(func.count(Position.id)).filter(Position.quantity > 0, Position.user_id.in_(real), Position.player_id.in_(orphans)).scalar()
            exposure += db.query(func.count(Order.id)).filter(Order.user_id.in_(real), Order.player_id.in_(orphans)).scalar()
        print(f"real-user exposure on those players: {exposure}")

        if not args.confirm:
            print("\nDry run only. Re-run with --confirm.")
            return
        if exposure:
            sys.exit("REFUSING: real users hold/ordered these players.")

        db.query(Tournament).filter(Tournament.id.in_(ids)).delete(synchronize_session=False)
        db.commit()
        print("Tournaments deleted.")
        # recompute orphans after the cascade (placements are gone now)
        orphans = [r[0] for r in db.query(Player.id).filter(~Player.id.in_(db.query(PlacementResult.player_id))).all()]
        for i in range(0, len(orphans), _CHUNK):
            db.query(Player).filter(Player.id.in_(orphans[i:i + _CHUNK])).delete(synchronize_session=False)
            db.commit()
        print(f"Deleted {len(orphans)} player(s) with no placements.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
