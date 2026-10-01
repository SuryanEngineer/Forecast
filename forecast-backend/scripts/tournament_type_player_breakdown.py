#!/usr/bin/env python3
"""
Read-only report (makes ZERO database writes) answering: "where are all
these 40k+ active players actually coming from?"

Breaks down, per TournamentType tier and per year (COALESCE across
start_time/end_time/created_at, same as deactivate_pre_cutoff_players.py),
how many distinct tracked Tournament rows exist and how many DISTINCT
players have a real PlacementResult in that tier/year. A player who placed
in more than one tier/year is counted once in each bucket they appear in
(this is a "where do players come from" breakdown, not a partition), so
the per-bucket numbers can legitimately add up to more than the total
active player count.

Why this exists: tournament_classification_service.py's DEFAULT_RULES
auto-tracks every "Cash Cup" family window (Reload Cash Cup, FNCS Division
practice finals, Performance Evaluation, generic Cash Cup) as real
Finals-tier, cash-payout tournaments -- not just rare top-tier events like
FNCS Finals / Global Championship / EWC. Cash Cups run roughly weekly, per
region, often in multiple formats, so there are very likely FAR more than
"100 tournaments a year" being tracked once you count every region/format
of Cash Cup. This report makes that visible instead of guessed at.

Usage:
    cd forecast-backend
    python3 scripts/tournament_type_player_breakdown.py
    python3 scripts/tournament_type_player_breakdown.py --year 2026
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, ".")

from sqlalchemy import extract, func  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.player import Player  # noqa: E402
from app.models.tournament import PlacementResult, Tournament, TournamentType  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--year", type=int, default=datetime.now(timezone.utc).year,
        help="Year to break down (default: current year). Pass 0 to show all years combined.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        total_active = db.query(func.count(Player.id)).filter(Player.is_active.is_(True)).scalar() or 0
        print(f"Total active players (all tiers, all years): {total_active}\n")

        tournament_year = func.coalesce(Tournament.start_time, Tournament.end_time, Tournament.created_at)

        # --- Tournament counts per type/year (is this tournament itself
        # excessively numerous, e.g. hundreds of Cash Cups?) ---
        t_query = db.query(
            Tournament.tournament_type,
            extract("year", tournament_year).label("yr"),
            func.count(Tournament.id),
        ).filter(Tournament.is_historical_archive.is_(False)).group_by(Tournament.tournament_type, "yr")
        tournament_counts: dict = defaultdict(int)
        for ttype, yr, count in t_query.all():
            tournament_counts[(ttype, int(yr) if yr is not None else None)] = count

        # --- Distinct real (placement-having) players per type/year ---
        p_query = (
            db.query(
                Tournament.tournament_type,
                extract("year", tournament_year).label("yr"),
                PlacementResult.player_id,
            )
            .join(PlacementResult, PlacementResult.tournament_id == Tournament.id)
            .distinct()
        )
        player_sets: dict = defaultdict(set)
        for ttype, yr, player_id in p_query.all():
            player_sets[(ttype, int(yr) if yr is not None else None)].add(player_id)

        years_seen = sorted({yr for (_, yr) in tournament_counts.keys() if yr is not None}, reverse=True)
        if args.year:
            years_seen = [y for y in years_seen if y == args.year]

        print(f"{'Tier':<22}{'Year':<8}{'Tournaments':<14}{'Distinct players':<18}{'Avg players/tourney':<20}")
        print("-" * 82)
        for ttype in TournamentType:
            for yr in years_seen:
                tcount = tournament_counts.get((ttype, yr), 0)
                pcount = len(player_sets.get((ttype, yr), set()))
                if tcount == 0 and pcount == 0:
                    continue
                avg = f"{pcount / tcount:.1f}" if tcount else "n/a"
                print(f"{ttype.value:<22}{yr:<8}{tcount:<14}{pcount:<18}{avg:<20}")

        print(
            "\nNote: a player who placed in more than one tier/year is counted once per bucket they "
            "appear in, so these numbers are NOT a clean partition of the total active count -- this "
            "is meant to show where the volume is coming from, not add up perfectly."
        )
        print(
            "\nIf CASH_CUP's tournament count for the target year is in the hundreds, that -- not a "
            "duplicate-player bug -- is most of why the active roster is larger than a naive "
            "'100 tournaments x 100 players' estimate would suggest: every region's weekly Cash Cup "
            "(see tournament_classification_service.py's DEFAULT_RULES) is currently tracked as a real, "
            "cash-payout Finals tier, same as FNCS Finals / Global Championship / EWC."
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
