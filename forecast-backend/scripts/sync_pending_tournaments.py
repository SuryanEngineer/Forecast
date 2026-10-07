#!/usr/bin/env python3
"""
Pull and finalize tournaments that are tracked but stuck in RESULTS_PENDING / SCHEDULED
(e.g. FNCS Division 1 rounds, Last Chance, Reload Elite Series, Global Championship 2026).

Same safe path as resync_roster.py: skip_finalize=True (marks FINALIZED, creates NO dividend payouts),
tournament flagged is_historical_archive=True while syncing so the live loop can't race it.
FINALS ONLY: for a multi-round event ("FNCS Division 1 — Round 1..4") just the highest-numbered round is synced;
earlier rounds and anything named "Practice" are skipped and hidden. Single events are their own final.
Scope rule is the same as reset_roster.py (--min-year, --regions NAC EU, LAN/global tier always counts,
Zero Build never). Only tournaments that have already started are touched.

Dry run by default (prints the plan). Add --confirm to sync.

    python3 scripts/sync_pending_tournaments.py
    python3 scripts/sync_pending_tournaments.py --confirm
    python3 scripts/sync_pending_tournaments.py --confirm --include-out-of-scope   # also other regions/older (roster players only)
    python3 scripts/sync_pending_tournaments.py --confirm --only "Global Championship"
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, ".")

from sqlalchemy import func  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.osirion import OsirionTournamentMapping  # noqa: E402
from app.models.tournament import PlacementResult, Tournament, TournamentStatus  # noqa: E402
from app.services import osirion_service  # noqa: E402
from scripts.deactivate_out_of_scope_players import _find_zero_build_tournament_ids  # noqa: E402
from scripts.reset_roster import classify_tournament  # noqa: E402


_ROUND_RE = re.compile(r"^(.*?)\s*[—–-]\s*Round\s+(\d+)\s*$", re.IGNORECASE)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--min-year", type=int, default=datetime.now().year)
    ap.add_argument("--regions", nargs="+", default=["NAC", "EU"])
    ap.add_argument("--include-out-of-scope", action="store_true",
                    help="Also sync out-of-scope tournaments, attaching results to existing players only.")
    ap.add_argument("--all-rounds", action="store_true", help="Don't restrict to final rounds (not recommended).")
    ap.add_argument("--only", default="", help="Only tournaments whose name contains this text.")
    ap.add_argument("--attempts", type=int, default=6)
    ap.add_argument("--retry-wait", type=int, default=30)
    args = ap.parse_args()
    regions = [r.strip().upper() for r in args.regions]
    now = datetime.now(timezone.utc)

    db = SessionLocal()
    db.expire_on_commit = False
    try:
        zb = set(_find_zero_build_tournament_ids(db).keys())
        pending = (
            db.query(Tournament, OsirionTournamentMapping)
            .join(OsirionTournamentMapping, OsirionTournamentMapping.tournament_id == Tournament.id)
            .filter(Tournament.status != TournamentStatus.FINALIZED)
            .order_by(Tournament.start_time.asc().nullslast())
            .all()
        )
        # FINALS ONLY: a multi-round event ("<base> — Round N") counts only through its highest-numbered
        # round; single events (no "Round N" suffix) are their own final. Practice events never count.
        every = db.query(Tournament.name, Tournament.start_time).join(
            OsirionTournamentMapping, OsirionTournamentMapping.tournament_id == Tournament.id).all()
        last_round: dict = {}
        for name, st in every:
            mt = _ROUND_RE.match(name or "")
            if mt:
                key = (mt.group(1).strip().lower(), st.year if st else None)
                last_round[key] = max(last_round.get(key, 0), int(mt.group(2)))

        def is_final(t: Tournament) -> tuple[bool, str]:
            if "practice" in (t.name or "").lower():
                return False, "practice"
            if "performance evaluation" in (t.name or "").lower():
                return False, "performance evaluation (excluded)"
            mt = _ROUND_RE.match(t.name or "")
            if not mt:
                return True, ""
            key = (mt.group(1).strip().lower(), t.start_time.year if t.start_time else None)
            if int(mt.group(2)) == last_round.get(key):
                return True, ""
            return False, f"not the last round ({last_round.get(key)})"

        plan = []
        hide = []
        print(f"{'action':<10} {'date':<11} {'status':<16} {'type':<20} {'region':<8}  name")
        for t, m in pending:
            if args.only and args.only.lower() not in t.name.lower():
                continue
            kind, reason = classify_tournament(t, zb, args.min_year, regions)
            started = t.start_time is not None and t.start_time <= now
            final, not_final_reason = is_final(t)
            if not args.all_rounds and not final and kind != "zero_build":
                kind, reason = "not_final", not_final_reason
            if not started:
                action = "not yet"
            elif kind == "not_final":
                action = "skip-nf"
                hide.append(t)
            elif kind == "in_scope":
                action = "SYNC"
            elif kind == "out_of_scope" and args.include_out_of_scope:
                action = "SYNC-hist"
            else:
                action = "skip"
            when = t.start_time or t.created_at
            print(f"{action:<10} {str(when.date()):<11} {t.status.value:<16} {t.tournament_type.value:<20} "
                  f"{str(t.region):<8}  {t.name}  [{reason}]")
            if action.startswith("SYNC"):
                plan.append((t, m, action == "SYNC"))
        print(f"\n{len(plan)} tournament(s) would be synced + finalized (no dividends).")
        if not args.confirm:
            print("Dry run only. Re-run with --confirm.")
            return

        for t in hide:  # non-final rounds / practice: hide from the public calendar, status untouched
            t.is_historical_archive = True
        db.commit()
        if hide:
            print(f"Hid {len(hide)} non-final round/practice tournament(s) (is_historical_archive=True, not synced).")

        failed = []
        for n, (t, m, create) in enumerate(plan, start=1):
            print(f"\n[{n}/{len(plan)}] {t.name!r} ...", flush=True)
            was_hist = bool(t.is_historical_archive)
            t.is_historical_archive = True
            m.last_sync_complete = False
            db.commit()
            finalized = False
            for attempt in range(1, args.attempts + 1):
                r = osirion_service.sync_tournament(db, m, skip_finalize=True, create_missing_players=create)
                print(f"    attempt {attempt}: {r.entries_seen} entries, {r.matched} matched, "
                      f"{len(r.unmatched_usernames)} unmatched"
                      + (f", ERROR: {r.error}" if r.error else "") + (", finalized" if r.finalized else ""))
                db.refresh(t)
                if r.finalized or t.status == TournamentStatus.FINALIZED:
                    finalized = True
                    break
                if not r.error:
                    print("    synced but not finalizable yet (window not ended / leaderboard incomplete per Osirion).")
                    break
                time.sleep(args.retry_wait)
            if finalized:
                t.is_historical_archive = was_hist
            else:
                failed.append(t.name)  # stays flagged historical = safe from the live loop
            db.commit()

        total_players = db.query(func.count(func.distinct(PlacementResult.player_id))).scalar()
        print(f"\nDone. Distinct players with placements now: {total_players}")
        if failed:
            print("Not finalized (left hidden/safe; re-run to retry): " + "; ".join(failed))
    finally:
        db.close()


if __name__ == "__main__":
    main()
