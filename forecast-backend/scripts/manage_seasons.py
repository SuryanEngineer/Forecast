#!/usr/bin/env python3
"""
Manage ranked seasons (the Seasonal Points ladder).

    cd forecast-backend
    python3 scripts/manage_seasons.py list
    python3 scripts/manage_seasons.py create "Chapter 7 Season 1" 2026-12-01 2027-03-01 --activate
    python3 scripts/manage_seasons.py create "Chapter 7 Season 2" 2027-03-01 2027-06-01      # scheduled; auto-activates
    python3 scripts/manage_seasons.py standings                                              # live standings
    python3 scripts/manage_seasons.py finalize                                               # end the active season now

Dates are UTC (YYYY-MM-DD or YYYY-MM-DDTHH:MM). The running server also rolls seasons over automatically: when the
active season passes its end date it is finalized (final points/rank stored) and a scheduled season whose window has
begun is activated. Everyone starts each season at 0 SP from their net worth at that moment.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

sys.path.insert(0, ".")

from app.db.session import SessionLocal  # noqa: E402
import app.models  # noqa: E402,F401
from app.models.account import Season  # noqa: E402
from app.services import season_service  # noqa: E402


def _dt(text: str) -> datetime:
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    raise SystemExit(f"Bad date {text!r}; use YYYY-MM-DD")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    c = sub.add_parser("create")
    c.add_argument("name"); c.add_argument("starts"); c.add_argument("ends"); c.add_argument("--activate", action="store_true")
    sub.add_parser("standings").add_argument("--top", type=int, default=20)
    sub.add_parser("finalize")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        if args.cmd == "list":
            for s in db.query(Season).order_by(Season.starts_at.desc()).all():
                state = "ACTIVE" if s.is_active else ("finalized" if s.finalized_at else "scheduled")
                print(f"{s.name:<30} {s.starts_at:%Y-%m-%d} -> {s.ends_at:%Y-%m-%d}  [{state}]")
        elif args.cmd == "create":
            s = season_service.create_season(db, args.name, _dt(args.starts), _dt(args.ends), activate=args.activate)
            db.commit()
            print(f"Created '{s.name}'" + (" and activated it (all users entered with their current net worth)." if args.activate else " (scheduled)."))
        elif args.cmd == "standings":
            s = season_service.get_active_season(db)
            if s is None:
                print("No active season."); return
            rows = season_service.season_standings(db, s)
            db.commit()
            print(f"{s.name}  (ends {s.ends_at:%Y-%m-%d})")
            for r in rows[:args.top]:
                print(f"{r['position']:>3}. {r['display_name']:<22} {r['rank_tier']:<10} {r['season_points']:>6} SP  {r['return_pct']:+.2f}%")
        elif args.cmd == "finalize":
            s = season_service.get_active_season(db)
            if s is None:
                print("No active season."); return
            n = season_service.finalize_season(db, s)
            db.commit()
            print(f"Finalized '{s.name}' ({n} entries stored).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
