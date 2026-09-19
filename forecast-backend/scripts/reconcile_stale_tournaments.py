#!/usr/bin/env python3
"""
One-time (safe to re-run) cleanup pass for tournament rows tracked BEFORE
the Finals-only/no-Zero-Build auto-track rewrite in
app/services/osirion_service.py (see that module's `auto_track_new_tournaments`
docstring). That rewrite only changed what gets tracked GOING FORWARD --
anything already sitting in the tournaments table from the old, unreliable
"trust Osirion's round number" logic stays exactly as broken as it was
(wrong names like "... — Round 0", heats/qualifiers/practice rounds and
Zero Build variants tracked as if they were real dividend-paying Finals,
stuck forever showing "upcoming" because they never actually finalize).
This script finds and fixes/removes that leftover mess. It does NOT touch
anything already FINALIZED -- a tournament that already paid out dividends
is left alone no matter what.

For every Tournament that is NOT yet finalized:

  1. No OsirionTournamentMapping at all (a manually/admin-created
     tournament) -- left alone, listed for visibility only.

  2. Has a mapping. Looks up that exact (event, window) in Osirion's
     current full listing (list_available_windows(include_historic_data=True),
     matched on osirion_event_id + osirion_event_window_id) and re-runs it
     through the SAME real production checks auto_track_new_tournaments
     itself uses (has_cash_payout / is_zero_build) -- no separate/duplicated
     logic that could drift from the real thing:

       - Not found in Osirion's listing at all -> Osirion no longer has
         any record of this window. Flagged ORPHANED.
       - Found, but has_cash_payout=False (a heat/qualifier/practice round
         that only pays advancement tokens, no real money) or
         is_zero_build=True -> this was never a real Finals window to
         begin with. Flagged INVALID.
       - Found and passes both checks -> a genuinely real Finals window.
         Runs a live sync_tournament() right now -- the exact same call
         the background sync loop makes every 45s -- and reports exactly
         what happened (entries seen/matched, and whether it finalized or
         why not), instead of guessing.

ORPHANED and INVALID tournaments have never finalized (by definition --
this script only ever looks at non-finalized ones), so no dividends have
ever been paid for them and deleting them is safe. Deleting a Tournament
row cascades automatically to its OsirionTournamentMapping,
PlacementResult, TournamentEntrant, and DividendPayout rows (all declared
ondelete="CASCADE" -- see app/models/tournament.py and
app/models/osirion.py).

This does NOT touch Player rows (including any zero-share placeholders
created by an older version of _match_player, back before "anyone found
in a tracked tournament gets a real stock" became the rule) -- a player
row being harmless clutter is a separate, much lower-stakes cleanup than
tournament data actively confusing the calendar/leaderboard UI.

Usage (dry run by default -- shows what it found and, for valid-but-stuck
tournaments, what a live sync attempt actually returns; deletes nothing):
    cd forecast-backend
    python3 scripts/reconcile_stale_tournaments.py

Actually delete the ORPHANED/INVALID tournaments found above (this still
also runs the live sync attempts on valid-but-stuck ones either way):
    python3 scripts/reconcile_stale_tournaments.py --confirm
"""
from __future__ import annotations

import argparse
import sys

sys.path.insert(0, ".")

from app.db.session import SessionLocal  # noqa: E402
from app.integrations.osirion_client import OsirionApiError  # noqa: E402
from app.models.osirion import OsirionTournamentMapping  # noqa: E402
from app.models.tournament import Tournament, TournamentStatus  # noqa: E402
from app.services import osirion_service  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--confirm", action="store_true",
        help="Actually delete ORPHANED/INVALID tournaments found. Without this flag, it's a dry run.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        pending = (
            db.query(Tournament)
            .filter(Tournament.status != TournamentStatus.FINALIZED)
            .order_by(Tournament.start_time.asc().nullslast())
            .all()
        )
        print(f"Found {len(pending)} non-finalized tournament(s) to check.\n")

        print("Fetching Osirion's current full tournament listing (includeHistoricData=true)...")
        try:
            current_windows = osirion_service.list_available_windows(include_historic_data=True)
        except OsirionApiError as exc:
            print(f"ERROR: could not reach Osirion at all -- aborting, nothing changed. ({exc})")
            return
        by_key = {(w.event_id, w.event_window_id): w for w in current_windows}
        print(f"Osirion currently lists {len(current_windows)} trackable window(s).\n")

        no_mapping: list[Tournament] = []
        orphaned: list[tuple[Tournament, OsirionTournamentMapping]] = []
        invalid: list[tuple[Tournament, OsirionTournamentMapping, str]] = []
        valid_synced = 0

        for t in pending:
            mapping = (
                db.query(OsirionTournamentMapping).filter(OsirionTournamentMapping.tournament_id == t.id).one_or_none()
            )
            if mapping is None:
                no_mapping.append(t)
                continue

            window = by_key.get((mapping.osirion_event_id, mapping.osirion_event_window_id))
            if window is None:
                orphaned.append((t, mapping))
                continue

            if window.is_zero_build:
                invalid.append((t, mapping, "Zero Build variant -- never a real dividend-paying tournament"))
                continue
            if not window.has_cash_payout:
                invalid.append((t, mapping, "heat/qualifier/practice round -- pays advancement tokens only, no real cash"))
                continue

            # A genuinely valid Finals window -- try syncing it right now,
            # the exact same call the background loop makes every 45s.
            result = osirion_service.sync_tournament(db, mapping)
            valid_synced += 1
            status_line = (
                f"  - {t.name!r} (id={t.id}, region={t.region}): "
                f"entries_seen={result.entries_seen} matched={result.matched} finalized={result.finalized}"
            )
            if result.error:
                status_line += f" ERROR={result.error!r}"
            if result.unmatched_usernames:
                status_line += f" unmatched={result.unmatched_usernames[:5]}"
            print(status_line)

        print(f"\n{valid_synced} tournament(s) are genuinely valid Finals windows -- synced live just now (see above).")

        if no_mapping:
            print(f"\n{len(no_mapping)} non-finalized tournament(s) have no Osirion mapping (manually created) -- left alone:")
            for t in no_mapping:
                print(f"  - {t.name!r} (id={t.id}, status={t.status.value})")

        if orphaned:
            print(f"\n{len(orphaned)} tournament(s) ORPHANED -- Osirion no longer lists this window at all:")
            for t, m in orphaned:
                print(f"  - {t.name!r} (id={t.id}, tracked event={m.osirion_event_id}/{m.osirion_event_window_id})")

        if invalid:
            print(f"\n{len(invalid)} tournament(s) INVALID -- never should have been tracked as real Finals:")
            for t, m, reason in invalid:
                print(f"  - {t.name!r} (id={t.id}): {reason}")

        to_delete = [t for t, _ in orphaned] + [t for t, _, _ in invalid]
        if not to_delete:
            print("\nNothing to delete.")
            return

        if not args.confirm:
            print(
                f"\nDry run only -- {len(to_delete)} tournament(s) would be deleted, nothing deleted yet. "
                "Re-run with --confirm to actually delete them."
            )
            return

        for t in to_delete:
            db.delete(t)
        db.commit()
        print(f"\nDeleted {len(to_delete)} tournament(s) (and everything that cascaded from them).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
