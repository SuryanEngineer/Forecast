#!/usr/bin/env python3
"""
Deactivates Player rows that only ever exist because of the (now-disabled)
qualifier/heat leaderboard pre-seeding -- see
app/services/osirion_service.py's `_seed_entrants_from_heat_windows`
docstring for the full story: it used to walk every qualifier/heat
window's FULL leaderboard (often tens of thousands of entrants, heavy on
one-off names) and auto-IPO everyone found, even though tournament
TRACKING itself was always correctly limited to genuine cash-payout
Finals events (~40-100 real entrants). That's why production ended up
with 89,702 Player rows. The decision going forward (per the user) is:
only Finals-tier tournaments with real cash payouts should ever create or
grow the tradeable player roster.

This script is the one-time cleanup for players ALREADY created that way.
Fixing osirion_service.py only stops new ones from being created; this
handles the ones already sitting in the database.

How a "qualifier-only" player is identified: every player who genuinely
appeared on a tracked Finals tournament's own leaderboard -- live or
finalized -- gets a real PlacementResult row for it (see
sync_tournament's per-page upsert_placement_result call, which runs
throughout a tournament's whole live-sync lifetime, not just after it
finalizes). So a Player with ZERO PlacementResult rows, across every
tournament, was NEVER seen on a real Finals leaderboard -- their only
footprint is a TournamentEntrant row from the disabled heat-seeding path
(i.e. they qualified for or competed in a qualifier/heat, but never
actually placed in the tracked Finals itself, at least not yet).

"Real user" here excludes both strategy bots (BotProfile rows) and the
House/market-maker system account (every player IPOs with 100% of its
shares owned by House -- see app/services/house_account.py -- so House
alone doesn't count as a real holder, only an actual person's Position
does).

What this script deliberately does NOT do: delete anything, or touch a
player any real (non-bot) user currently holds shares in. Deleting would
destroy the OsirionPlayerMapping/audit trail for no benefit; touching a
real holding would mean unwinding someone's actual position, which is
exactly the kind of automatic financial-data surgery this codebase has
avoided elsewhere (see clean_player_gamertags.py / reconcile_stale_
tournaments.py's module docstrings for the same principle). Instead:
  - Zero-PlacementResult players with NO real-user Position (quantity>0)
    get `is_active = False` (not deleted) -- this is the exact flag
    market_data_service.list_market_snapshots already filters on, so
    they immediately stop appearing anywhere in the market/leaderboard
    UI, while everything about them (mapping, entrant history, gamertag)
    stays intact and reversible.
  - Zero-PlacementResult players that a real user DOES hold shares in are
    left untouched and printed separately for manual review -- likely
    rare (bots mostly trade players with real price history), but if it
    happens, a human should decide, not this script.

Usage (dry run by default -- shows what would be deactivated, changes
nothing):
    cd forecast-backend
    python3 scripts/deactivate_qualifier_only_players.py

Actually apply the deactivation found above:
    python3 scripts/deactivate_qualifier_only_players.py --confirm

To undo (re-activate everything this script touched), see the printed
id list in its output -- there's no automatic "undo" mode, on purpose,
since re-activating should be a deliberate per-player decision too.
"""
from __future__ import annotations

import argparse
import sys

sys.path.insert(0, ".")

from sqlalchemy import func  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.player import Player, Position  # noqa: E402
from app.models.tournament import PlacementResult  # noqa: E402
from app.models.bot import BotProfile  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.house_account import HOUSE_ACCOUNT_EMAIL  # noqa: E402


def _players_with_any_placement(db: Session) -> set:
    rows = db.query(PlacementResult.player_id).distinct().all()
    return {r[0] for r in rows}


def _players_with_real_holdings(db: Session) -> set:
    """Players a real (non-bot, non-House) user currently holds shares in
    -- these are left alone no matter what, see module docstring.

    Excludes both strategy bots (app.models.bot.BotProfile) AND the
    House/market-maker system account (app.services.house_account) --
    every single player IPOs with 100% of its shares owned by House (see
    that module's docstring), so without excluding it too, EVERY player
    in the database would always show a "real" holder and nothing would
    ever be classified as safe to deactivate. This mirrors the same
    House+bot exclusion pattern already used in
    app/services/leaderboard_service.py."""
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
    real_holder_rows = query.distinct().all()
    return {r[0] for r in real_holder_rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--confirm", action="store_true",
        help="Actually deactivate the players found. Without this flag, it's a dry run that only prints what it found.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        total_active = db.query(func.count(Player.id)).filter(Player.is_active.is_(True)).scalar() or 0
        placed_ids = _players_with_any_placement(db)

        candidates = (
            db.query(Player)
            .filter(Player.is_active.is_(True))
            .filter(Player.id.notin_(placed_ids) if placed_ids else True)
            .all()
        )

        if not candidates:
            print(f"Total active players: {total_active}. Nothing to do -- every active player has at least one real placement result.")
            return

        real_holder_ids = _players_with_real_holdings(db)

        to_deactivate = [p for p in candidates if p.id not in real_holder_ids]
        needs_review = [p for p in candidates if p.id in real_holder_ids]

        print(f"Total active players: {total_active}")
        print(f"Players with zero placement results (never seen on a real Finals leaderboard): {len(candidates)}")
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
        # A bulk UPDATE ... WHERE id IN (...) in chunks, NOT one UPDATE per
        # ORM object -- setting `.is_active` on tens of thousands of loaded
        # Player instances and committing sends one round trip per row to
        # the database, which against a remote connection (this app talks
        # to a hosted Supabase Postgres, not a local DB) can take minutes
        # to tens of minutes for a batch this size. `synchronize_session`
        # is set to False since these Player objects aren't read again
        # after this point. Chunked (not one single WHERE id IN (44,661
        # values)) to stay well clear of any single-statement parameter
        # limits.
        CHUNK_SIZE = 2000
        for start in range(0, len(ids_deactivated), CHUNK_SIZE):
            chunk = ids_deactivated[start : start + CHUNK_SIZE]
            db.query(Player).filter(Player.id.in_(chunk)).update(
                {"is_active": False}, synchronize_session=False
            )
            db.commit()

        remaining_active = db.query(func.count(Player.id)).filter(Player.is_active.is_(True)).scalar() or 0
        print(f"\nDeactivated {len(ids_deactivated)} player(s). Active players: {total_active} -> {remaining_active}.")
        print("(Nothing was deleted -- re-activate any of these later by setting is_active back to True if needed.)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
