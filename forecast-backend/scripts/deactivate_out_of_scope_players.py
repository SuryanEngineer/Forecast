#!/usr/bin/env python3
"""
Deactivates (never deletes) Player rows that have no real placement
matching the CURRENT product scope: a tournament dated `--min-year` (default:
the current year) or later, that is EITHER in one of `--regions` (default:
NAC, EU) OR a LAN/global tier (FNCS Global Championship, EWC, Major) --
LAN tiers are never region-restricted, since they're inherently
cross-region events (see app/services/osirion_service.py's
ALLOWED_TRACKING_REGIONS/_in_tracking_region_scope, which this script's
`--regions` default mirrors).

This supersedes scripts/deactivate_pre_cutoff_players.py -- that script
only checked year, not region/LAN-tier, which can wrongly spare a player
whose only recent placement is in a region no longer in scope (e.g. an
OCE Cash Cup from this year) by combining a year check and a separate
region check in two independent passes. This script checks both
conditions on the SAME placement at once, which is the only way to get
the combined filter right (see this file's own `_players_in_scope` for
why doing the checks independently is a bug, not just a style choice).
If you already ran deactivate_pre_cutoff_players.py, that's fine --
re-running this one is still correct and will catch anything that
two-pass approach missed.

ALSO excludes any placement from a Zero Build (ZB) tournament -- see
`_find_zero_build_tournament_ids` below. Zero Build tournaments are
supposed to NEVER be auto-tracked (see osirion_service._is_zero_build),
but that check only runs on the automatic auto-track path, not on a
tournament tracked manually via the admin UI -- so a legacy manually
-tracked ZB tournament can still be sitting in the database counting
toward the active roster. Confirmed in production: one such tournament
("Console Duos ZB Cash Cup") alone accounted for 16,141 of ~16,622 total
2026 Cash Cup players -- a real Finals lobby is 40-350 real entrants, not
16,000+, and the "ZB" marker is right there in its own name/eventId.

A player's "year" is COALESCE(Tournament.start_time, Tournament.end_time,
Tournament.created_at), same as deactivate_pre_cutoff_players.py. A
LAN/global-tier placement counts regardless of what Tournament.region
happens to be recorded as (often None or a single arbitrary region even
though the event draws from everywhere).

Same safety rules as every other script in this folder: never deletes,
never touches a player any real (non-bot, non-House) user currently holds
shares in (flagged for manual review instead), and is a dry run unless you
pass --confirm.

Usage (dry run by default):
    cd forecast-backend
    python3 scripts/deactivate_out_of_scope_players.py

Actually apply it:
    python3 scripts/deactivate_out_of_scope_players.py --confirm

Different scope (e.g. once a third region is added later):
    python3 scripts/deactivate_out_of_scope_players.py --min-year 2026 --regions NAC EU OCE --confirm
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

sys.path.insert(0, ".")

from sqlalchemy import extract, func, or_  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.bot import BotProfile  # noqa: E402
from app.models.osirion import OsirionTournamentMapping  # noqa: E402
from app.models.player import Player, Position  # noqa: E402
from app.models.tournament import PlacementResult, Tournament, TournamentType  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.house_account import HOUSE_ACCOUNT_EMAIL  # noqa: E402

# Mirrors app/services/osirion_service.py's _REGION_EXEMPT_TOURNAMENT_TYPES
# -- kept as a separate constant (not imported) so this script has no
# import-time dependency on that module; keep both in sync if the LAN tier
# set ever changes.
LAN_TOURNAMENT_TYPES = (TournamentType.GLOBAL_CHAMPIONSHIP, TournamentType.MAJOR)

# Mirrors app/services/osirion_service.py's _ZERO_BUILD_MARKERS (not
# imported, same reasoning as above). Checked against every text field
# Osirion's own naming convention could carry a "ZB" marker in -- see
# osirion_service._is_zero_build's docstring for why it's spread across
# eventGroup/eventId/display name/playlistId there; here we only have
# what actually got persisted (Tournament.name, and the tracked mapping's
# own ids/display name), which is enough since all of those observed
# "ZB" tournaments carry the marker directly in their name/eventId.
_ZERO_BUILD_MARKERS = ("zb", "no build", "nobuild", "no-build")


def _find_zero_build_tournament_ids(db: Session) -> dict:
    """Returns {tournament_id: tournament_name} for every tracked
    Tournament whose own name or Osirion mapping ids/display name contain
    a Zero Build marker. These should never have been auto-tracked (see
    osirion_service._is_zero_build) -- this exists because that check only
    runs on the AUTOMATIC track path, not on a tournament tracked manually
    via the admin UI, so a legacy manually-tracked ZB tournament can still
    be sitting in the database. This function only FINDS them -- see this
    script's main() for what happens to players whose only placements come
    from one of these; the Tournament row itself is never touched here
    (if it's already FINALIZED, real dividends may already have been paid
    out on it -- unwinding that is a separate, deliberately-not-automated
    decision, same reasoning as every other script in this folder)."""
    found: dict = {}
    rows = (
        db.query(Tournament.id, Tournament.name, OsirionTournamentMapping.leaderboard_event_id,
                  OsirionTournamentMapping.leaderboard_event_window_id, OsirionTournamentMapping.osirion_display_name)
        .outerjoin(OsirionTournamentMapping, OsirionTournamentMapping.tournament_id == Tournament.id)
        .all()
    )
    for tournament_id, name, leaderboard_event_id, leaderboard_event_window_id, osirion_display_name in rows:
        haystack = " ".join(
            filter(None, [name, leaderboard_event_id, leaderboard_event_window_id, osirion_display_name])
        ).lower()
        if any(marker in haystack for marker in _ZERO_BUILD_MARKERS):
            found[tournament_id] = name
    return found


def _players_in_scope(db: Session, min_year: int, regions: list[str], zero_build_tournament_ids: set) -> set:
    """Players with at least one real placement that is dated min_year-or-later
    AND (region in `regions` OR a LAN/global tier) AND NOT from a Zero Build
    tournament -- all checked on the SAME placement/tournament row, not as
    independent filters. Doing any of these as separate passes (keep if any
    placement is recent; separately, keep if any placement is in-region;
    separately, keep if any placement isn't ZB) would wrongly spare a player
    whose only recent, in-region placement happens to be from a ZB
    tournament and whose only non-ZB placement is stale/out-of-region --
    no single placement actually satisfies every real requirement, but a
    naive multi-pass check would let different placements each satisfy one
    condition and incorrectly treat the player as in scope."""
    tournament_year = func.coalesce(Tournament.start_time, Tournament.end_time, Tournament.created_at)
    upper_regions = [r.strip().upper() for r in regions]
    query = (
        db.query(PlacementResult.player_id)
        .join(Tournament, Tournament.id == PlacementResult.tournament_id)
        .filter(extract("year", tournament_year) >= min_year)
        .filter(
            or_(
                func.upper(Tournament.region).in_(upper_regions),
                Tournament.tournament_type.in_(LAN_TOURNAMENT_TYPES),
            )
        )
    )
    if zero_build_tournament_ids:
        query = query.filter(Tournament.id.notin_(zero_build_tournament_ids))
    rows = query.distinct().all()
    return {r[0] for r in rows}


def _players_with_real_holdings(db: Session) -> set:
    """Same as every other cleanup script's helper -- players a real
    (non-bot, non-House) user currently holds shares in. Duplicated here
    rather than imported, same reasoning as deactivate_pre_cutoff_players.py."""
    bot_user_ids = {r[0] for r in db.query(BotProfile.user_id).all()}
    house_row = db.query(User.id).filter(User.email == HOUSE_ACCOUNT_EMAIL).one_or_none()
    if house_row is not None:
        bot_user_ids.add(house_row[0])

    rows = db.query(Position.player_id).filter(Position.quantity > 0).distinct().all()
    candidate_ids = {r[0] for r in rows}
    if not candidate_ids:
        return set()
    query = db.query(Position.player_id).filter(Position.player_id.in_(candidate_ids), Position.quantity > 0)
    if bot_user_ids:
        query = query.filter(Position.user_id.notin_(bot_user_ids))
    return {r[0] for r in query.distinct().all()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--min-year", type=int, default=datetime.now(timezone.utc).year,
        help="Keep players with at least one in-scope placement in this year or later (default: current year).",
    )
    parser.add_argument(
        "--regions", nargs="+", default=["NAC", "EU"],
        help="Region codes (besides LAN/global-tier placements, which always count) that keep a player in "
             "scope. Default: NAC EU -- matches osirion_service.ALLOWED_TRACKING_REGIONS.",
    )
    parser.add_argument(
        "--confirm", action="store_true",
        help="Actually deactivate the players found. Without this flag, it's a dry run that only prints what it found.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        total_active = db.query(func.count(Player.id)).filter(Player.is_active.is_(True)).scalar() or 0

        zero_build_tournaments = _find_zero_build_tournament_ids(db)
        if zero_build_tournaments:
            print(f"Found {len(zero_build_tournaments)} tracked tournament(s) with a Zero Build marker "
                  "in their name/ids -- placements from these never count toward scope:")
            for tid, name in zero_build_tournaments.items():
                pcount = db.query(func.count(PlacementResult.id)).filter(PlacementResult.tournament_id == tid).scalar() or 0
                print(f"  - id={tid}  name={name!r}  placements={pcount}")
            print()

        in_scope_ids = _players_in_scope(db, args.min_year, args.regions, set(zero_build_tournaments.keys()))

        candidates = (
            db.query(Player)
            .filter(Player.is_active.is_(True))
            .filter(Player.id.notin_(in_scope_ids) if in_scope_ids else True)
            .all()
        )

        regions_str = "/".join(args.regions)
        if not candidates:
            print(
                f"Total active players: {total_active}. Nothing to do -- every active player has a "
                f"{args.min_year}+ placement that's either {regions_str} or a LAN/global tier."
            )
            return

        real_holder_ids = _players_with_real_holdings(db)

        to_deactivate = [p for p in candidates if p.id not in real_holder_ids]
        needs_review = [p for p in candidates if p.id in real_holder_ids]

        print(f"Total active players: {total_active}")
        print(f"In scope ({args.min_year}+, {regions_str}, or LAN/global tier): {len(in_scope_ids)}")
        print(f"Out of scope: {len(candidates)}")
        print(f"  -> safe to deactivate (no real user holds shares): {len(to_deactivate)}")
        print(f"  -> held by a real user, left alone, needs manual review: {len(needs_review)}")

        if needs_review:
            print("\nFlagged for manual review (NOT touched):")
            for p in needs_review[:50]:
                print(f"  - id={p.id}  gamertag={p.gamertag!r}")
            if len(needs_review) > 50:
                print(f"  ... and {len(needs_review) - 50} more")

        if not to_deactivate:
            print("\nNothing to deactivate.")
            return

        if not args.confirm:
            print(f"\nDry run only -- nothing changed. Sample of what would be deactivated (showing up to 20 of {len(to_deactivate)}):")
            for p in to_deactivate[:20]:
                print(f"  - id={p.id}  gamertag={p.gamertag!r}")
            print("\nRe-run with --confirm to actually deactivate these players (sets is_active=False; nothing is deleted).")
            return

        ids_deactivated = [p.id for p in to_deactivate]
        # Bulk UPDATE in chunks, not one UPDATE per ORM object -- see
        # deactivate_qualifier_only_players.py's commit for why (against a
        # remote database, one round trip per row can take minutes).
        CHUNK_SIZE = 2000
        for start in range(0, len(ids_deactivated), CHUNK_SIZE):
            chunk = ids_deactivated[start : start + CHUNK_SIZE]
            db.query(Player).filter(Player.id.in_(chunk)).update({"is_active": False}, synchronize_session=False)
            db.commit()

        remaining_active = db.query(func.count(Player.id)).filter(Player.is_active.is_(True)).scalar() or 0
        print(f"\nDeactivated {len(ids_deactivated)} player(s). Active players: {total_active} -> {remaining_active}.")
        print("(Nothing was deleted -- re-activate any of these later by setting is_active back to True if needed.)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
