#!/usr/bin/env python3
"""
Deactivates (never deletes) Player rows whose real Finals placements are
ALL from before a cutoff year -- default: keep only players who placed in
a real (cash-payout, tracked) Finals tournament in 2026 or later.

Why this exists: `scripts/deactivate_qualifier_only_players.py` already
cuts the roster down to players who've genuinely appeared on a real
Finals leaderboard at least once, ever. That's still a lot of players --
this app has been tracking (and, via the historical backfill feature,
back-filling) results across more than one season, and a real Fortnite
competitive scene has real season-over-season roster turnover: someone
who placed in a 2024 or 2025 Cash Cup and never showed up again isn't
someone actively competing right now. Per explicit product direction,
the live tradeable market should reflect the CURRENT competitive season
only -- 2026 Finals-tier results -- not the full historical archive.

A player's "year" is taken from the tournament(s) they actually placed
in: COALESCE(Tournament.start_time, Tournament.end_time,
Tournament.created_at), since start_time/end_time are both nullable on
older/manually-entered rows. A player is KEPT if ANY of their real
placements falls in `--min-year` (default: the current year) or later;
they're only a deactivation candidate if EVERY placement they have is
strictly older than that.

Same safety rules as deactivate_qualifier_only_players.py: never
deletes, never touches a player any real (non-bot, non-House) user
currently holds shares in (flagged for manual review instead), and is a
dry run unless you pass --confirm.

Usage (dry run by default):
    cd forecast-backend
    python3 scripts/deactivate_pre_cutoff_players.py

Actually apply it:
    python3 scripts/deactivate_pre_cutoff_players.py --confirm

To use a different cutoff year (e.g. once 2027 starts and last season's
players should roll off too):
    python3 scripts/deactivate_pre_cutoff_players.py --min-year 2027 --confirm
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

sys.path.insert(0, ".")

from sqlalchemy import extract, func  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.player import Player, Position  # noqa: E402
from app.models.tournament import PlacementResult, Tournament  # noqa: E402
from app.models.bot import BotProfile  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.house_account import HOUSE_ACCOUNT_EMAIL  # noqa: E402


def _players_with_recent_placement(db: Session, min_year: int) -> set:
    """Players with at least one real placement in a tournament dated
    `min_year` or later (COALESCE across start_time/end_time/created_at
    since the first two are nullable)."""
    tournament_year = func.coalesce(Tournament.start_time, Tournament.end_time, Tournament.created_at)
    rows = (
        db.query(PlacementResult.player_id)
        .join(Tournament, Tournament.id == PlacementResult.tournament_id)
        .filter(extract("year", tournament_year) >= min_year)
        .distinct()
        .all()
    )
    return {r[0] for r in rows}


def _players_with_real_holdings(db: Session) -> set:
    """Same as deactivate_qualifier_only_players.py's helper -- players a
    real (non-bot, non-House) user currently holds shares in. Duplicated
    here rather than imported so this script has no import-time
    dependency on that one; keep both in sync if the exclusion logic
    ever changes."""
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
        help="Keep players with at least one real placement in this year or later (default: current year).",
    )
    parser.add_argument(
        "--confirm", action="store_true",
        help="Actually deactivate the players found. Without this flag, it's a dry run that only prints what it found.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        total_active = db.query(func.count(Player.id)).filter(Player.is_active.is_(True)).scalar() or 0
        recent_ids = _players_with_recent_placement(db, args.min_year)

        candidates = (
            db.query(Player)
            .filter(Player.is_active.is_(True))
            .filter(Player.id.notin_(recent_ids) if recent_ids else True)
            .all()
        )

        if not candidates:
            print(f"Total active players: {total_active}. Nothing to do -- every active player has a placement in {args.min_year} or later.")
            return

        real_holder_ids = _players_with_real_holdings(db)

        to_deactivate = [p for p in candidates if p.id not in real_holder_ids]
        needs_review = [p for p in candidates if p.id in real_holder_ids]

        print(f"Total active players: {total_active}")
        print(f"Players with no real placement in {args.min_year} or later: {len(candidates)}")
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
