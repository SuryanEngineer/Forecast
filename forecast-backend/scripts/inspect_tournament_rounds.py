#!/usr/bin/env python3
"""
Read-only inspector (makes ZERO writes) over the RAW Osirion metadata this
app already archived for its own tracked tournaments -- see
TournamentResultArchive.raw_tournament_metadata, captured once at
track_tournament time (see osirion_service.track_tournament). No new
Osirion API calls are made here; this just prints what Osirion already
told this app about each tournament's round structure.

Why this exists: auto_track_new_tournaments currently picks ONE window per
Osirion event -- whichever has the single highest real-cash payout (see
osirion_service.auto_track_new_tournaments / _pick_score_location) -- and
treats its entire leaderboard as "the tournament". For a genuinely
multi-round event (heats -> a real Finals lobby), that's only correct if
the highest-paying window IS the real Finals round. Live Osirion data
confirms this isn't always safe to assume: an earlier round can ALSO have
a real (non-token) USD payout table, and round numbers aren't consistent
across event types (some use round=0 for every day of a multi-day LAN).

This script prints, for each currently-tracked tournament (optionally
filtered by --type and/or --year), EVERY eventWindow Osirion originally
reported for that event (not just the one that got tracked) -- its round
number, begin/end time, and whether it's the one this app actually chose
to track -- plus a summary of the chosen window's payout table (how many
distinct payout thresholds it has, and the lowest one's reward) and the
actual distinct-player count this app ended up with from it. That's
enough to see, per tournament, whether "the Finals round" and "the window
we tracked" are the same thing, and how deep the real cash line goes.

Usage:
    cd forecast-backend
    python3 scripts/inspect_tournament_rounds.py
    python3 scripts/inspect_tournament_rounds.py --type cash_cup --year 2026
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

sys.path.insert(0, ".")

from sqlalchemy import extract, func  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.osirion import OsirionTournamentMapping  # noqa: E402
from app.models.tournament import PlacementResult, Tournament, TournamentResultArchive, TournamentType  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--type", type=str, default="cash_cup", help="TournamentType value to filter to (default: cash_cup). Pass 'all' for every type.")
    parser.add_argument("--year", type=int, default=datetime.now(timezone.utc).year, help="Year to filter to (default: current year). Pass 0 for all years.")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        query = db.query(Tournament)
        if args.type != "all":
            query = query.filter(Tournament.tournament_type == TournamentType(args.type))
        if args.year:
            tournament_year = func.coalesce(Tournament.start_time, Tournament.end_time, Tournament.created_at)
            query = query.filter(extract("year", tournament_year) == args.year)
        tournaments = query.order_by(Tournament.start_time).all()

        if not tournaments:
            print("No matching tournaments found.")
            return

        print(f"Found {len(tournaments)} matching tournament(s).\n")

        for t in tournaments:
            mapping = db.query(OsirionTournamentMapping).filter(OsirionTournamentMapping.tournament_id == t.id).one_or_none()
            archive = db.query(TournamentResultArchive).filter(TournamentResultArchive.tournament_id == t.id).one_or_none()
            player_count = (
                db.query(func.count(func.distinct(PlacementResult.player_id)))
                .filter(PlacementResult.tournament_id == t.id)
                .scalar()
                or 0
            )

            print("=" * 100)
            print(f"{t.name}  (id={t.id}, region={t.region}, type={t.tournament_type.value})")
            print(f"  Tracked window: leaderboard_event_id={mapping.leaderboard_event_id if mapping else 'N/A'}  "
                  f"leaderboard_event_window_id={mapping.leaderboard_event_window_id if mapping else 'N/A'}")
            print(f"  Distinct players from this tournament: {player_count}")

            if archive is None or not archive.raw_tournament_metadata:
                print("  No raw metadata archived for this tournament (tracked before archival was added, or never captured).")
                continue

            raw_tournament = archive.raw_tournament_metadata.get("tournament") or {}
            raw_event_window = archive.raw_tournament_metadata.get("event_window") or {}
            all_windows = raw_tournament.get("eventWindows", [])

            print(f"  Osirion eventId: {raw_tournament.get('eventId')}  eventGroup: {raw_tournament.get('eventGroup')}")
            print(f"  This event had {len(all_windows)} total eventWindow(s) in Osirion's data:")
            for w in all_windows:
                is_tracked_window = w.get("eventWindowId") == raw_event_window.get("eventWindowId")
                marker = " <-- THIS IS THE ONE TRACKED" if is_tracked_window else ""
                score_locs = w.get("scoreLocations", [])
                cash_summary = []
                for sl in score_locs:
                    tables = sl.get("payoutTables") or []
                    for table in tables:
                        ranks = table.get("ranks") or []
                        if not ranks:
                            continue
                        reward_types = {p.get("rewardType") for r in ranks for p in (r.get("payouts") or [])}
                        thresholds = sorted((r.get("threshold") for r in ranks if r.get("threshold") is not None))
                        cash_summary.append(f"table has {len(ranks)} threshold(s), reward types={reward_types}, "
                                             f"threshold range={thresholds[:1]}..{thresholds[-1:]}")
                cash_str = "; ".join(cash_summary) if cash_summary else "no payout tables"
                print(f"    - eventWindowId={w.get('eventWindowId')}  round={w.get('round')}  "
                      f"begin={w.get('beginTime')}  end={w.get('endTime')}  [{cash_str}]{marker}")
            print()
    finally:
        db.close()


if __name__ == "__main__":
    main()
