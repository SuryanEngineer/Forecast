#!/usr/bin/env python3
"""
List an upcoming event on the calendar BEFORE Osirion publishes it (for example the FNCS Solo Reload Finals).

It creates an ordinary scheduled tournament marked as a placeholder. When Osirion later publishes the real window (same tier,
starting within 36 hours of the date you give), the tracker links the placeholder to it automatically -- same tournament, no
duplicate -- and it syncs, finishes and pays like any other.

    python3 scripts/add_placeholder_event.py --name "FNCS Solo Reload Finals" --type fncs_finals --start "2026-11-21 19:00" --region NAC
    python3 scripts/add_placeholder_event.py --name "FNCS Solo Reload Finals" --type fncs_finals --start "2026-11-21 19:00" --region EU --confirm

Times are UTC. --type is one of: fncs_finals, fncs_qualifier, cash_cup, major, global_championship, performance_eval.
Dry run by default.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")

from app.db.session import SessionLocal  # noqa: E402
from app.models.tournament import Tournament, TournamentType  # noqa: E402
from app.services import economic_params_service, tournament_service  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", required=True)
    ap.add_argument("--type", required=True, choices=[t.value for t in TournamentType])
    ap.add_argument("--start", required=True, help="UTC, 'YYYY-MM-DD HH:MM'")
    ap.add_argument("--hours", type=float, default=4.0, help="Length in hours (default 4)")
    ap.add_argument("--region", default=None, help="NAC, EU, ... (omit for a multi-region event)")
    ap.add_argument("--confirm", action="store_true")
    args = ap.parse_args()

    start = datetime.strptime(args.start, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    ttype = TournamentType(args.type)
    db = SessionLocal()
    try:
        pool = economic_params_service.get_fixed_tournament_pool(db, ttype, args.region)
        if pool is not None:
            pool = pool * economic_params_service.get_region_multiplier(db, args.region)
        print(f"{args.name}  [{ttype.value}]  {start:%Y-%m-%d %H:%M} UTC  region={args.region or 'multi'}  pool={'$' + format(pool, ',.0f') if pool else 'n/a'}")
        dupe = db.query(Tournament).filter(Tournament.tournament_type == ttype, Tournament.region == args.region).all()
        for t in dupe:
            if t.start_time and abs((t.start_time.replace(tzinfo=timezone.utc) if not t.start_time.tzinfo else t.start_time) - start) < timedelta(hours=36):
                print(f"  already exists nearby: {t.name} ({t.start_time:%Y-%m-%d %H:%M}) -- not adding another")
                return
        if not args.confirm:
            print("Dry run only. Re-run with --confirm to add it.")
            return
        t = tournament_service.create_tournament(
            db, name=args.name, tournament_type=ttype, region=args.region, start_time=start, end_time=start + timedelta(hours=args.hours),
        )
        db.commit()
        print(f"Added (id {t.id}). It will be linked to Osirion's window automatically once that is published.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
