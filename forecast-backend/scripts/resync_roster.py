#!/usr/bin/env python3
"""
STEP 2 OF 2 of a full roster reset (see scripts/reset_roster.py): re-pull every
tournament that was finalized before the wipe, straight from Osirion, which
re-creates every Player and every PlacementResult from scratch.

It uses the exact same code path a live sync uses (osirion_service.sync_tournament:
fetch the leaderboard, create/match players by Osirion account id, write placements)
but with skip_finalize=True, so NO dividends are paid for these already-decided
results -- the same safety the historical backfill uses.

Per tournament (oldest first):
  1. un-finalize it and flag it is_historical_archive=True. The flag matters: the
     deployed backend's 45-second sync loop skips historical-archive tournaments, so it
     can never race in and pay real dividends on a result that is being re-pulled.
  2. run sync_tournament(skip_finalize=True) until it finalizes (retrying a few times on
     Osirion errors / rate limits).
  3. restore the tournament's original is_historical_archive flag.
Progress is saved to roster_reset_state.json after each tournament, so if it stops
(rate limits, laptop sleeping, Ctrl+C) just run it again and it resumes. A tournament
that is interrupted mid-way is left flagged historical (still safe from the loop) and is
redone on the next run.

Afterwards, in this order:
    python3 scripts/deactivate_out_of_scope_players.py --confirm   # roster scope (2026, NAC/EU + LAN)
    python3 scripts/merge_from_linker.py                           # dry run first, then --confirm
    python3 scripts/kickstart_market.py                            # optional: let bots reprice

Usage:
    cd forecast-backend
    python3 scripts/resync_roster.py
    python3 scripts/resync_roster.py --only "Global Championship"   # just matching names
    python3 scripts/resync_roster.py --with-history                 # + older/other-region results for roster players only

By default ONLY in-scope tournaments (per the scope table reset_roster.py printed) are re-pulled, so the roster is
rebuilt at its proper size (hundreds), not the ~89k a full re-pull would create. Zero Build is never re-pulled.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, ".")

from app.db.session import SessionLocal  # noqa: E402
from app.models.osirion import OsirionTournamentMapping  # noqa: E402
from app.models.tournament import Tournament, TournamentStatus  # noqa: E402
from app.services import osirion_service  # noqa: E402

STATE_FILE = Path("roster_reset_state.json")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", default="", help="Only tournaments whose name contains this text (case-insensitive).")
    parser.add_argument("--attempts", type=int, default=6, help="Sync attempts per tournament before moving on (default 6).")
    parser.add_argument("--retry-wait", type=int, default=30, help="Seconds to wait between failed attempts (default 30).")
    parser.add_argument("--with-history", action="store_true",
                        help="After the in-scope tournaments, also re-pull out-of-scope (older / other-region) non-Zero-Build "
                             "tournaments, attaching results ONLY to players already on the roster -- never creating new players.")
    args = parser.parse_args()

    if not STATE_FILE.exists():
        sys.exit(f"{STATE_FILE} not found. Run scripts/reset_roster.py --confirm first (from this same directory).")
    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    done = set(state.get("done", []))
    all_entries = state["tournaments"]

    # Phase 1 = in-scope (creates players). Phase 2 = out-of-scope history (existing players only). Zero Build = never.
    if any("scope" not in t for t in all_entries):
        sys.exit("State file has no scope info (it was written by the old reset_roster.py). Refusing: re-pulling "
                 "everything would recreate ~89k players. Add a \"scope\" field to each tournament, or ask for help.")
    phase1 = [t for t in all_entries if t["scope"] == "in_scope"]
    phase2 = [t for t in all_entries if t.get("scope") == "out_of_scope"] if args.with_history else []
    skipped = [t for t in all_entries if t not in phase1 and t not in phase2]
    for t in phase1:
        t["_create"] = True
    for t in phase2:
        t["_create"] = False
    todo = [t for t in phase1 + phase2 if t["id"] not in done]
    if args.only:
        todo = [t for t in todo if args.only.lower() in t["name"].lower()]
    print(f"{len(done)} tournament(s) already re-pulled; {len(todo)} to go "
          f"({len(phase1)} in-scope, {len(phase2)} history-only, {len(skipped)} skipped).\n")

    db = SessionLocal()
    db.expire_on_commit = False
    failed = []
    try:
        for n, entry in enumerate(todo, start=1):
            tid = uuid.UUID(entry["id"])
            tournament = db.get(Tournament, tid)
            mapping = db.query(OsirionTournamentMapping).filter(OsirionTournamentMapping.tournament_id == tid).one_or_none()
            if tournament is None or mapping is None:
                print(f"[{n}/{len(todo)}] {entry['name']!r}: tournament or Osirion mapping no longer exists -- skipped.")
                failed.append(entry["name"])
                continue

            print(f"[{n}/{len(todo)}] {tournament.name!r} ...", flush=True)
            tournament.status = TournamentStatus.RESULTS_PENDING
            tournament.is_historical_archive = True  # keeps the live sync loop away (see module docstring)
            mapping.last_sync_complete = False
            mapping.last_synced_at = None
            db.commit()

            finalized = False
            for attempt in range(1, args.attempts + 1):
                result = osirion_service.sync_tournament(
                    db, mapping, skip_finalize=True, create_missing_players=entry["_create"]
                )
                print(f"    attempt {attempt}: {result.entries_seen} entries, {result.matched} matched, "
                      f"{len(result.unmatched_usernames)} unmatched"
                      + (f", ERROR: {result.error}" if result.error else "") + (", finalized" if result.finalized else ""))
                if result.finalized:
                    finalized = True
                    break
                db.refresh(tournament)
                if tournament.status == TournamentStatus.FINALIZED:
                    finalized = True
                    break
                if not result.error:
                    break  # no error but not finalized (e.g. window hasn't ended) -- retrying won't help
                time.sleep(args.retry_wait)

            if finalized:
                tournament.is_historical_archive = bool(entry["was_historical_archive"])
                db.commit()
                done.add(entry["id"])
                state["done"] = sorted(done)
                STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
            else:
                print("    NOT finalized -- left flagged historical (safe). Re-run this script to retry it.")
                failed.append(tournament.name)

        # Tournaments we deliberately do not rebuild stay hidden from the public list (historical archive)
        # and un-finalized, so the live sync loop and the Tournaments page never touch them.
        if not args.only:
            for entry in skipped:
                t = db.get(Tournament, uuid.UUID(entry["id"]))
                if t is not None and not t.is_historical_archive:
                    t.is_historical_archive = True
            db.commit()
            if skipped:
                print(f"\nSkipped (hidden, not rebuilt): " + "; ".join(f"{t['name']} [{t.get('scope_reason', t.get('scope'))}]" for t in skipped))

        print(f"\nDone. {len(done)}/{len(phase1) + len(phase2)} planned tournament(s) re-pulled.")
        if failed:
            print("Not finished (re-run to retry): " + ", ".join(failed))
        else:
            print("Everything re-pulled. Next: deactivate_out_of_scope_players.py --confirm, then merge_from_linker.py.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
