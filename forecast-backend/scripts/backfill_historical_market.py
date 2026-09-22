#!/usr/bin/env python3
"""
Populates the market from Osirion's historical tournament data: for every
already-decided, real cash-paying Finals window that isn't tracked yet,
creates a real tradeable Player stock for every competitor found, writes
permanent PlacementResult rows for their finish, and archives the raw
leaderboard (TournamentResultArchive) -- all the same real, tested code
path a live sync uses (see app/services/osirion_service.py's
_match_player/sync_tournament).

Safe by design in two ways:

  1. Never triggers a real dividend payout. A live tournament pays
     dividends to whoever holds shares AT finalize time -- that only makes
     sense for a result nobody could have traded around in advance. A
     historical result is, by definition, already decided, so naively
     finalizing it the normal way would let someone buy shares right
     before the backfill and collect a payout for a result that already
     happened. Every tournament this script tracks goes through
     sync_tournament(..., skip_finalize=True): still a full real sync,
     just marks the tournament FINALIZED directly instead of calling
     tournament_service.finalize_tournament, so zero DividendPayout rows
     are ever created for backfilled data.

  2. Never clutters the live Tournaments page. Every tournament this
     script creates is marked is_historical_archive=True (see that
     column's docstring on the Tournament model), which the public
     GET /tournaments list explicitly filters out. A player's backfilled
     results are still fully visible on their own history endpoint
     (GET /tournaments/players/{id}/history queries PlacementResult
     directly, unaffected by this flag) -- this is deliberately the hook
     point for the in-depth per-player research/analytics view planned
     for later; nothing further needs to change there when that gets
     built.

Eligibility mirrors the live auto-tracking rules (real cash payout, not
Zero Build, one window per event picked by the highest-paying window,
must match a classification rule) with one difference: no season/region
dedup -- history wants every distinct past edition it can find, not just
one per season.

Interruption-safe: if this script (or your network connection) dies
mid-run, nothing is lost -- each leaderboard page commits to the database
as it's fetched -- and nothing dangerous happens either -- a tournament
that was mid-sync when interrupted just sits non-finalized, and nothing
else in this app will ever touch it (see resume_incomplete_historical_backfills's
docstring for why). Just run this exact same command again: every run
starts by automatically finishing any historical tournament left
incomplete by an earlier interrupted run, before looking for new ones.

Usage (dry run by default -- shows what's eligible, tracks/syncs nothing):
    cd forecast-backend
    python3 scripts/backfill_historical_market.py

Actually track + sync up to --limit (default 20) of the eligible windows
found above. Each one walks a full paginated leaderboard against Osirion's
shared, rate-limited API, so this is deliberately capped -- re-run as many
times as you want; already-tracked windows are skipped automatically, so
each run just picks up where the last one left off:
    python3 scripts/backfill_historical_market.py --confirm
    python3 scripts/backfill_historical_market.py --confirm --limit 50
"""
from __future__ import annotations

import argparse
import sys

sys.path.insert(0, ".")

from app.db.session import SessionLocal  # noqa: E402
from app.services import osirion_service  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--confirm", action="store_true",
        help="Actually track+sync eligible historical windows. Without this flag, it's a dry run.",
    )
    parser.add_argument(
        "--limit", type=int, default=20,
        help="Max number of NEW historical tournaments to track+sync in this run (default: 20). "
        "Only applies with --confirm.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        # Always resume first, dry run or not -- finishing a tournament
        # that was already tracked by an earlier interrupted run is just
        # completing safe, already-in-flight work (never creates a
        # dividend payout either), not a new destructive action, so it
        # doesn't need to wait for --confirm. Safe/cheap to call even when
        # there's nothing to resume. See resume_incomplete_historical_backfills's
        # docstring for why this exists at all: nothing else ever revisits
        # a historical tournament that got tracked but didn't finish
        # syncing (e.g. this script got interrupted -- lost network,
        # closed the terminal, etc.) part way through.
        resumed = osirion_service.resume_incomplete_historical_backfills(db)
        if resumed:
            print(f"Resuming {len(resumed)} historical tournament(s) left incomplete by an earlier run...")
            for r in resumed:
                print(
                    f"  - tournament {r.tournament_id}: entries_seen={r.entries_seen} matched={r.matched} "
                    f"finalized={r.finalized} error={r.error!r}"
                )
            print()

        print("Fetching Osirion's full historical tournament listing (includeHistoricData=true)...")
        scan = osirion_service.find_historical_backfill_candidates(db)
        if scan.errors:
            print(f"ERROR: could not reach Osirion at all -- aborting, nothing changed. ({scan.errors[0]})")
            return

        print(
            f"\n{scan.events_seen} distinct historical event(s) with a real cash payout found. "
            f"{scan.already_tracked} already tracked, {scan.skipped_not_eligible} not eligible "
            "(heat/qualifier, Zero Build, or not concluded yet), "
            f"{scan.skipped_unclassified} not matched by any classification rule.\n"
        )

        if not scan.candidates:
            print("Nothing new to backfill.")
            return

        print(f"{len(scan.candidates)} historical tournament(s) are eligible to backfill:")
        for c in scan.candidates[:30]:
            print(f"  - {c.window.display_name!r} -> {c.tournament_type.value} (top payout ${c.window.top_cash_amount})")
        if len(scan.candidates) > 30:
            print(f"  ... and {len(scan.candidates) - 30} more")

        if not args.confirm:
            print(
                f"\nDry run only -- nothing tracked yet. Re-run with --confirm to actually track+sync up to "
                f"--limit (default 20) of these. Each one walks a full Osirion leaderboard, so this is capped "
                "on purpose -- re-run as many times as you like; already-tracked windows are skipped "
                "automatically on the next run."
            )
            return

        batch = scan.candidates[: args.limit]
        print(f"\nTracking + syncing {len(batch)} historical tournament(s) now (this can take a while)...\n")
        result = osirion_service.backfill_historical_tournaments(db, batch)

        for line in result.tracked_details:
            print(f"  - {line}")

        if result.errors:
            print(f"\n{len(result.errors)} error(s) while backfilling:")
            for err in result.errors:
                print(f"  - {err}")

        print(
            f"\nBackfilled {result.tracked} historical tournament(s) -- "
            f"{result.total_entries_seen} leaderboard entries seen, {result.total_matched} matched to a real "
            "player/stock. Zero dividend payouts were created (backfill always skips finalize_tournament)."
        )
        remaining = len(scan.candidates) - len(batch)
        if remaining > 0:
            print(f"{remaining} more eligible historical tournament(s) remain -- re-run --confirm to continue.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
