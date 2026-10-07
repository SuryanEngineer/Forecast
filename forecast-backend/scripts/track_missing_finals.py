#!/usr/bin/env python3
"""
Find tournaments that exist in Osirion's history but were never tracked in this database (e.g. EWC, FNCS Finals),
keep only the ones that belong on the roster, then track + sync them with NO dividends.

Why not just backfill_historical_market.py? That one tracks EVERY eligible past window -- including every
cash cup, which is how the roster ballooned to ~89k players. This wrapper applies the roster scope first:

  * finals only: one window per event (the highest-paying one) -- same as the backfill scan
  * dated --min-year or later (default: current year)
  * region NAC/EU (--regions) or LAN/global tier (global_championship / major)
  * never Zero Build, never "Performance Evaluation", never "Practice"
  * cash-cup-typed events are skipped unless the name contains "FNCS" (--include-cash-cups lifts this)

Dry run by default: prints every candidate with its verdict and the reason. --confirm tracks+syncs the KEEP rows.
New tournaments are created hidden (is_historical_archive=True) and FINALIZED without payouts, same as the backfill.

    python3 scripts/track_missing_finals.py                  # dry run
    python3 scripts/track_missing_finals.py --show-skipped   # also list what was filtered out (and why)
    python3 scripts/track_missing_finals.py --confirm
    python3 scripts/track_missing_finals.py --confirm --only "Esports World Cup"
"""
from __future__ import annotations

import argparse
import sys
import time

sys.path.insert(0, ".")

from app.db.session import SessionLocal  # noqa: E402
from app.models.tournament import TournamentType  # noqa: E402
from app.services import osirion_service  # noqa: E402

_LAN_TYPES = (TournamentType.GLOBAL_CHAMPIONSHIP, TournamentType.MAJOR)


def _verdict(c, min_year: int, regions: list[str], include_cash_cups: bool) -> tuple[bool, str]:
    w = c.window
    name = w.display_name.lower()
    if "performance evaluation" in name:
        return False, "performance evaluation"
    if "practice" in name:
        return False, "practice"
    if w.is_zero_build:
        return False, "zero build"
    when = w.begin_time or w.end_time
    if when is None or when.year < min_year:
        return False, f"before {min_year}"
    is_lan = c.tournament_type in _LAN_TYPES
    in_region = any(r.upper() in regions for r in w.regions) if w.regions else False
    if not (is_lan or in_region):
        return False, f"region {w.regions} not in {regions}"
    if c.tournament_type == TournamentType.CASH_CUP and not include_cash_cups and "fncs" not in name:
        return False, "cash cup (not FNCS)"
    return True, "LAN/global tier" if is_lan else f"region {','.join(w.regions)}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--min-year", type=int, default=time.gmtime().tm_year)
    ap.add_argument("--regions", nargs="+", default=["NAC", "EU"])
    ap.add_argument("--include-cash-cups", action="store_true")
    ap.add_argument("--show-skipped", action="store_true")
    ap.add_argument("--only", default="", help="Only candidates whose name contains this text.")
    ap.add_argument("--attempts", type=int, default=6)
    ap.add_argument("--retry-wait", type=int, default=30)
    args = ap.parse_args()
    regions = [r.strip().upper() for r in args.regions]

    db = SessionLocal()
    db.expire_on_commit = False
    try:
        print("Fetching Osirion's historical listing ...")
        scan = osirion_service.find_historical_backfill_candidates(db)
        if scan.errors:
            sys.exit(f"Could not reach Osirion: {scan.errors[0]}")
        print(f"{scan.events_seen} cash-paying event(s); {scan.already_tracked} already tracked; "
              f"{scan.skipped_unclassified} unclassified; {len(scan.candidates)} untracked candidate(s).\n")

        keep, skipped = [], []
        for c in scan.candidates:
            if args.only and args.only.lower() not in c.window.display_name.lower():
                continue
            ok, why = _verdict(c, args.min_year, regions, args.include_cash_cups)
            (keep if ok else skipped).append((c, why))
        keep.sort(key=lambda t: t[0].window.begin_time or t[0].window.end_time)

        print(f"KEEP ({len(keep)}):")
        for c, why in keep:
            w = c.window
            print(f"  {str((w.begin_time or w.end_time).date()):<11} {c.tournament_type.value:<20} "
                  f"${w.top_cash_amount:>10,.0f}  {w.display_name}  [{why}]")
        print(f"\nFILTERED OUT: {len(skipped)}")
        if args.show_skipped:
            for c, why in sorted(skipped, key=lambda t: t[0].window.begin_time or t[0].window.end_time):
                w = c.window
                print(f"  {str((w.begin_time or w.end_time).date()):<11} {c.tournament_type.value:<20} {w.display_name}  [{why}]")
        else:
            reasons: dict[str, int] = {}
            for _, why in skipped:
                key = why.split(" [")[0] if not why.startswith("region") else "region out of scope"
                reasons[key] = reasons.get(key, 0) + 1
            for k, v in sorted(reasons.items(), key=lambda kv: -kv[1]):
                print(f"  {v:>4}  {k}")
            print("  (add --show-skipped to list them)")

        if not args.confirm:
            print("\nDry run only. Re-run with --confirm to track + sync the KEEP rows (no dividends).")
            return

        for n, (c, _) in enumerate(keep, start=1):
            w = c.window
            print(f"\n[{n}/{len(keep)}] {w.display_name!r} ...", flush=True)
            region = w.regions[0] if len(w.regions) == 1 else None
            mapping = osirion_service.track_tournament(
                db, name=w.display_name, tournament_type=c.tournament_type, region=region,
                window=w, created_by_admin_id=None, is_historical_archive=True,
            )
            for attempt in range(1, args.attempts + 1):
                r = osirion_service.sync_tournament(db, mapping, skip_finalize=True)
                print(f"    attempt {attempt}: {r.entries_seen} entries, {r.matched} matched"
                      + (f", ERROR: {r.error}" if r.error else "") + (", finalized" if r.finalized else ""))
                if r.finalized or not r.error:
                    break
                time.sleep(args.retry_wait)
        print("\nDone. Re-run list_tournaments.py --year 2026, then deactivate_out_of_scope_players.py.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
