#!/usr/bin/env python3
"""
Renames existing Player.gamertag values through the same clean_gamertag()
normalization osirion_service.py now applies at match/create time (see
that function's docstring) -- strips bracketed clan/LAN tags like
"[FNCSGC26]" or "[EW2026]" and collapses stray whitespace.

Why this script exists: that cleaning only affects players matched/created
AFTER the code change. Anyone already in the database was created earlier
with Osirion's raw username baked verbatim into their permanent (and
globally unique) gamertag -- this is a one-time pass to clean up whatever
is already there.

What it deliberately does NOT do: merge two players into one. If cleaning
two different players' gamertags would make them collide (e.g. one row is
already "PlayerName" and another is "[FNCSGC26] PlayerName", which cleans
to the same string), that's very likely the SAME real competitor sitting
in two separate Player rows with two separate stocks/share pools/holders
-- but merging that automatically would mean moving real share ownership
between stocks, which is exactly the kind of automatic financial-data
surgery this codebase has deliberately avoided elsewhere (see
reconcile_stale_tournaments.py's module docstring for a similar case).
Any such collision is only ever reported here, never merged -- go look at
the two rows by hand and decide (or ask an admin to island one clan-tagged
listing out with a manual note) before touching share data.

Usage (dry run by default -- shows what would be renamed, changes nothing):
    cd forecast-backend
    python3 scripts/clean_player_gamertags.py

Actually apply the renames found above:
    python3 scripts/clean_player_gamertags.py --confirm
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict

sys.path.insert(0, ".")

from app.db.session import SessionLocal  # noqa: E402
from app.models.player import Player  # noqa: E402
from app.services.osirion_service import clean_gamertag  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--confirm", action="store_true",
        help="Actually apply the renames found. Without this flag, it's a dry run that only prints what it found.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        players = db.query(Player).order_by(Player.gamertag).all()

        # Group every player by what their gamertag WOULD BE after cleaning
        # (case-insensitively, matching the ilike matching osirion_service.py
        # actually uses) so a collision is caught whether it's two already-
        # existing rows or one row colliding with another that doesn't need
        # any renaming at all.
        groups: dict[str, list[tuple[Player, str]]] = defaultdict(list)
        for player in players:
            cleaned = clean_gamertag(player.gamertag)
            groups[cleaned.lower()].append((player, cleaned))

        to_rename: list[tuple[Player, str, str]] = []  # (player, old, new)
        collisions: list[list[tuple[Player, str]]] = []

        for entries in groups.values():
            if len(entries) > 1:
                collisions.append(entries)
                continue
            player, cleaned = entries[0]
            if cleaned != player.gamertag:
                to_rename.append((player, player.gamertag, cleaned))

        if collisions:
            print(f"Found {len(collisions)} collision group(s) -- NOT touched, needs manual review:")
            for entries in collisions:
                print(f"  These {len(entries)} player(s) would all clean to the same name:")
                for player, cleaned in entries:
                    print(f"    - id={player.id}  gamertag={player.gamertag!r}  -> would be {cleaned!r}")
            print()

        if not to_rename:
            print("Nothing to rename.")
            return

        print(f"Found {len(to_rename)} player(s) whose gamertag would be cleaned up:")
        for player, old, new in to_rename:
            print(f"  - id={player.id}  {old!r} -> {new!r}")

        if not args.confirm:
            print("\nDry run only -- nothing renamed. Re-run with --confirm to actually apply the renames listed above.")
            return

        for player, _old, new in to_rename:
            player.gamertag = new
        db.commit()
        print(f"\nRenamed {len(to_rename)} player(s).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
