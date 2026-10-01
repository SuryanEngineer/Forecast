#!/usr/bin/env python3
"""
Report-only scan for Player rows that are likely the SAME real competitor
sitting in two or more separate stocks -- never merges or changes
anything, just prints what it found for a human to review.

Why this can happen despite osirion_service.py's accountId-based dedup
(see _match_player's docstring): the FIRST time a given Osirion accountId
is seen, there's no existing OsirionPlayerMapping row for it yet, so the
code falls back to an exact (case-insensitive) match against
Player.gamertag on the CLEANED username. That match is a byte-for-byte
comparison -- if an existing player's gamertag in the database is still
the OLD, uncleaned form (e.g. "[FNCSGC26] PlayerName", created before
clean_gamertag() existed, or before scripts/clean_player_gamertags.py was
last run), a new competitor's freshly-cleaned username "PlayerName" will
NOT match it, and a second Player row gets created for what is very
likely the same real person. Two different accountIds can also
legitimately be the same human (an alt/smurf account), which this script
can surface but can never be sure about -- that's exactly why this is a
report, not an auto-fix.

This script looks for TWO different kinds of evidence, independently:

1. EXACT collisions -- two or more active players whose gamertag, after
   running through the same clean_gamertag() normalization
   osirion_service.py itself uses, are identical (case-insensitive).
   This is the same grouping clean_player_gamertags.py already does for
   its rename pass; if you haven't run that script's --confirm yet, run
   it FIRST (it fixes the "stale uncleaned gamertag" root cause above for
   future matches) and then re-run this one -- some of what shows up here
   may just be solved by that.

2. LIKELY matches -- two or more active players whose gamertags become
   identical after a much more aggressive normalization (lowercase,
   strip ALL spaces/punctuation/symbols, not just clan-tag brackets).
   This catches cosmetic styling differences real Fortnite players often
   add/drop between events (stray unicode marks, extra numbers, dots,
   dashes) that clean_gamertag() deliberately does NOT strip, since
   stripping trailing digits/symbols from EVERY name would risk merging
   two genuinely different people who happen to share a plain name.
   These are lower-confidence than group 1 -- read the sample gamertags
   yourself before deciding anything.

For every group found, this prints each player's id, raw gamertag,
how many Osirion account-id mappings they have, how many real placements
they have, and their most recent placement's tournament name/date --
enough context to tell "yes, obviously the same person" from "no,
coincidence" by eye. It intentionally never merges players automatically
-- see clean_player_gamertags.py's module docstring for why that's
dangerous (merging moves real share ownership between stocks).

Usage:
    cd forecast-backend
    python3 scripts/find_duplicate_players.py
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict

sys.path.insert(0, ".")

from sqlalchemy import func  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.osirion import OsirionPlayerMapping  # noqa: E402
from app.models.player import Player  # noqa: E402
from app.models.tournament import PlacementResult, Tournament  # noqa: E402
from app.services.osirion_service import clean_gamertag  # noqa: E402

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def _loose_key(cleaned: str) -> str:
    """Aggressive normalization for the lower-confidence 'likely match'
    pass -- lowercase, strip everything that isn't a letter or digit."""
    return _NON_ALNUM_RE.sub("", cleaned.lower())


def main() -> None:
    db = SessionLocal()
    try:
        players = db.query(Player).filter(Player.is_active.is_(True)).order_by(Player.gamertag).all()
        if not players:
            print("No active players.")
            return

        # Per-player context, fetched in bulk (not N+1) up front.
        mapping_counts: dict = defaultdict(int)
        for player_id, count in db.query(OsirionPlayerMapping.player_id, func.count(OsirionPlayerMapping.id)).group_by(
            OsirionPlayerMapping.player_id
        ):
            mapping_counts[player_id] = count

        placement_counts: dict = defaultdict(int)
        for player_id, count in db.query(PlacementResult.player_id, func.count(PlacementResult.id)).group_by(
            PlacementResult.player_id
        ):
            placement_counts[player_id] = count

        latest_placement: dict = {}
        rows = (
            db.query(PlacementResult.player_id, Tournament.name, Tournament.start_time, Tournament.end_time, Tournament.created_at)
            .join(Tournament, Tournament.id == PlacementResult.tournament_id)
            .all()
        )
        for player_id, name, start_time, end_time, created_at in rows:
            when = start_time or end_time or created_at
            prev = latest_placement.get(player_id)
            if prev is None or (when and (prev[1] is None or when > prev[1])):
                latest_placement[player_id] = (name, when)

        def describe(p: Player) -> str:
            mcount = mapping_counts.get(p.id, 0)
            pcount = placement_counts.get(p.id, 0)
            latest = latest_placement.get(p.id)
            latest_str = f"{latest[0]} ({latest[1].date()})" if latest and latest[1] else (latest[0] if latest else "none")
            return (
                f"id={p.id}  gamertag={p.gamertag!r}  osirion_mappings={mcount}  "
                f"placements={pcount}  most_recent={latest_str}"
            )

        # --- Pass 1: exact collisions on clean_gamertag() ---
        exact_groups: dict = defaultdict(list)
        for p in players:
            exact_groups[clean_gamertag(p.gamertag).lower()].append(p)
        exact_collisions = [g for g in exact_groups.values() if len(g) > 1]

        print(f"Total active players scanned: {len(players)}\n")
        print(f"=== Pass 1: EXACT collisions after clean_gamertag() normalization ({len(exact_collisions)} group(s)) ===")
        if not exact_collisions:
            print("None found. (If you haven't run scripts/clean_player_gamertags.py --confirm yet, do that first -- it may surface more of these.)")
        for group in exact_collisions:
            print(f"\n  These {len(group)} player(s) normalize to the same cleaned gamertag:")
            for p in group:
                print(f"    - {describe(p)}")

        # --- Pass 2: loose matches (lower confidence) ---
        loose_groups: dict = defaultdict(list)
        for p in players:
            loose_groups[_loose_key(clean_gamertag(p.gamertag))].append(p)
        # Exclude groups already fully reported as exact collisions so the
        # output isn't doubled up.
        exact_key_set = {clean_gamertag(p.gamertag).lower() for group in exact_collisions for p in group}
        loose_only = [
            g for g in loose_groups.values()
            if len(g) > 1 and not all(clean_gamertag(p.gamertag).lower() in exact_key_set for p in g)
        ]

        print(f"\n\n=== Pass 2: LIKELY matches after aggressive normalization ({len(loose_only)} group(s)) -- lower confidence, review by eye ===")
        if not loose_only:
            print("None found.")
        for group in loose_only:
            print(f"\n  These {len(group)} player(s) look similar once punctuation/symbols/case are ignored:")
            for p in group:
                print(f"    - {describe(p)}")

        print(
            "\n\nNothing was changed. These are candidates for YOU to review -- merging player "
            "stocks moves real share ownership and is deliberately not automated here."
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
