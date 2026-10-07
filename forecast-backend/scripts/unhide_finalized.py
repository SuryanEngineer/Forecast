#!/usr/bin/env python3
"""
Make finalized, result-bearing 2026 tournaments visible on the public Tournaments page.

discover_finals.py tracks past finals as is_historical_archive=True (hidden) as a safety flag. Once a tournament is
FINALIZED with placements, nothing will ever sync or pay dividends on it again (sync_tournament returns immediately
for FINALIZED), so it is safe to show. This clears the hidden flag for FINALIZED tournaments that have an Osirion
mapping and at least one placement, dated --min-year or later. It never touches non-finalized tournaments.

Dry run by default.

    python3 scripts/unhide_finalized.py
    python3 scripts/unhide_finalized.py --confirm
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime

sys.path.insert(0, ".")

from sqlalchemy import exists, extract, func  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.osirion import OsirionTournamentMapping  # noqa: E402
from app.models.tournament import PlacementResult, Tournament, TournamentStatus  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--min-year", type=int, default=datetime.now().year)
    args = ap.parse_args()

    db = SessionLocal()
    try:
        when = func.coalesce(Tournament.start_time, Tournament.end_time, Tournament.created_at)
        rows = (
            db.query(Tournament)
            .filter(Tournament.status == TournamentStatus.FINALIZED)
            .filter(Tournament.is_historical_archive.is_(True))
            .filter(extract("year", when) >= args.min_year)
            .filter(exists().where(OsirionTournamentMapping.tournament_id == Tournament.id))
            .filter(exists().where(PlacementResult.tournament_id == Tournament.id))
            .order_by(Tournament.start_time.asc().nullslast())
            .all()
        )
        print(f"{len(rows)} finalized, hidden tournament(s) with results:")
        for t in rows:
            print(f"  {str(t.start_time.date()) if t.start_time else '?':<11} {t.tournament_type.value:<20} {t.name}")
        if not args.confirm:
            print("\nDry run only. Re-run with --confirm to make them visible.")
            return
        for t in rows:
            t.is_historical_archive = False
        db.commit()
        print(f"\nMade {len(rows)} tournament(s) visible.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
