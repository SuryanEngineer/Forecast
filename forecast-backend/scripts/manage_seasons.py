#!/usr/bin/env python3
"""
Manage ranked seasons (the Seasonal Points ladder).

    cd forecast-backend
    python3 scripts/manage_seasons.py list
    python3 scripts/manage_seasons.py sync-calendar                                          # load the Fortnite calendar (app/services/season_calendar.py)
    python3 scripts/manage_seasons.py create "Chapter 8: Season 2" 2027-03-01 TBD             # TBD = end not announced yet
    python3 scripts/manage_seasons.py set "Chapter 8: Season 1" --ends 2027-03-01T09:00        # fix a start/end (UTC)
    python3 scripts/manage_seasons.py delete "Some Season" --confirm                           # remove a mistaken season
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
    c.add_argument("name"); c.add_argument("starts"); c.add_argument("ends", help="date, or TBD"); c.add_argument("--activate", action="store_true")
    c.add_argument("--kind", default="season", choices=["season", "mini"])
    sub.add_parser("sync-calendar")
    st = sub.add_parser("set"); st.add_argument("name"); st.add_argument("--starts"); st.add_argument("--ends", help="date, or TBD")
    dl = sub.add_parser("delete"); dl.add_argument("name"); dl.add_argument("--confirm", action="store_true")
    sub.add_parser("standings").add_argument("--top", type=int, default=20)
    sub.add_parser("finalize")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        if args.cmd == "list":
            for s in db.query(Season).order_by(Season.starts_at.desc()).all():
                state = "ACTIVE" if s.is_active else ("finalized" if s.finalized_at else "scheduled")
                end = f"{s.ends_at:%Y-%m-%d %H:%M}" if s.ends_at else "TBD"
                print(f"{s.name:<34} {s.kind:<7} {s.starts_at:%Y-%m-%d %H:%M} -> {end:<16} [{state}]")
        elif args.cmd == "create":
            ends = None if args.ends.upper() == "TBD" else _dt(args.ends)
            s = season_service.create_season(db, args.name, _dt(args.starts), ends, activate=args.activate, kind=args.kind)
            db.commit()
            print(f"Created '{s.name}'" + (" and activated it (all users entered with their current net worth)." if args.activate else " (scheduled)."))
        elif args.cmd == "sync-calendar":
            from app.services import season_calendar
            for line in season_calendar.sync_calendar(db) or ["nothing to change"]:
                print(" ", line)
            db.commit()
            print("Done. Run `python3 scripts/manage_seasons.py list` to check.")
        elif args.cmd == "set":
            s = db.query(Season).filter(Season.name == args.name).first()
            if s is None:
                print(f"No season named {args.name!r}."); return
            if args.starts:
                s.starts_at = _dt(args.starts)
            if args.ends:
                s.ends_at = None if args.ends.upper() == "TBD" else _dt(args.ends)
            if s.ends_at is not None and s.ends_at <= s.starts_at:
                db.rollback(); print("End must be after start."); return
            for line in season_service.run_rollover(db):
                print(" ", line)
            db.commit()
            print(f"Updated '{s.name}'.")
        elif args.cmd == "delete":
            s = db.query(Season).filter(Season.name == args.name).first()
            if s is None:
                print(f"No season named {args.name!r}."); return
            if not args.confirm:
                print(f"Would delete '{s.name}' and its entries. Re-run with --confirm."); return
            db.delete(s)
            db.commit()
            print(f"Deleted '{args.name}'. Run sync-calendar to activate the right season.")
        elif args.cmd == "standings":
            s = season_service.get_active_season(db)
            if s is None:
                print("No active season."); return
            rows = season_service.season_standings(db, s)
            db.commit()
            print(f"{s.name}  (ends {s.ends_at:%Y-%m-%d})" if s.ends_at else f"{s.name}  (end date TBD)")
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
