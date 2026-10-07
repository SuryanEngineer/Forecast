#!/usr/bin/env python3
"""Read-only: every Tournament in the DB (any status), with mapping, archive flag and placement count.
Use it to see what's tracked vs. what you expect (e.g. EWC 2026, 2026 Global Championship, FNCS).

    python3 scripts/list_tournaments.py
    python3 scripts/list_tournaments.py --year 2026
"""
from __future__ import annotations

import argparse
import sys

sys.path.insert(0, ".")

from sqlalchemy import func  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.osirion import OsirionTournamentMapping  # noqa: E402
from app.models.tournament import PlacementResult, Tournament  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=None)
    args = ap.parse_args()
    db = SessionLocal()
    try:
        counts = dict(db.query(PlacementResult.tournament_id, func.count(PlacementResult.id)).group_by(PlacementResult.tournament_id).all())
        mapped = {r[0] for r in db.query(OsirionTournamentMapping.tournament_id).all()}
        rows = db.query(Tournament).order_by(Tournament.start_time.asc().nullslast()).all()
        print(f"{'date':<11} {'status':<16} {'type':<20} {'region':<8} {'map':<4} {'hist':<5} {'rows':>6}  name")
        for t in rows:
            when = t.start_time or t.end_time or t.created_at
            if args.year and (when is None or when.year != args.year):
                continue
            print(f"{str(when.date()) if when else '?':<11} {t.status.value:<16} {t.tournament_type.value:<20} "
                  f"{str(t.region):<8} {'yes' if t.id in mapped else 'no':<4} {'yes' if t.is_historical_archive else '':<5} "
                  f"{counts.get(t.id, 0):>6}  {t.name}")
        print(f"\n{len(rows)} tournament(s) total.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
