#!/usr/bin/env python3
"""
HARD-DELETES (not just deactivates) Player rows left over from earlier
bot/liquidity testing in this codebase -- gamertags starting with
"TestPro", "FixedPoolPro", "AuctionPro", or "ThinLiquidityPro" (confirmed
in production: 11 such rows, flagged by
scripts/deactivate_out_of_scope_players.py's "held by a real user" review
list because a test bot/account -- not a real Fortnite competitor --
currently holds shares in them).

This is a DELIBERATE exception to every other script in this folder's
"never delete, only deactivate" rule: that rule exists to protect REAL
financial/competitive history (a real player's real placements, a real
user's real trade history against them) from being destroyed. These
rows have none of that -- they were synthetically created by test
scripts (never a real Osirion sync), never had a real placement, and
exist purely as fixtures for earlier bot-liquidity testing. Deactivating
them would just leave permanent clutter in the players table forever;
deleting is the correct cleanup once they're confirmed to be test data
and nothing else.

Deletion is a single bulk `DELETE FROM players WHERE id IN (...)` (not
an ORM-level `db.delete()` loop) specifically so it relies on the
database's own `ON DELETE CASCADE` (declared on every players.id foreign
key -- Position, Order/OrderFill, OsirionPlayerMapping, PlacementResult,
DividendPayout, AuctionListing -- see each model) to clean up related rows
automatically, rather than SQLAlchemy's ORM cascade machinery trying to
load and null out NOT NULL foreign keys first (the exact NOT NULL
violation scripts/reconcile_stale_tournaments.py hit the hard way, see
that script's docstring). This removes each synthetic player's test
positions/orders along with it -- the holding user/bot account itself is
never touched, it just ends up with one less (fake) position.

Matching is by GAMERTAG PREFIX, not a hardcoded id list -- so if the same
test-fixture pattern ever creates more rows later (e.g. a re-run of
whatever test script made these), this script still finds them. If you
ever have a LEGITIMATE real competitor whose gamertag happens to start
with one of these prefixes (vanishingly unlikely, but technically
possible), check the dry-run output before confirming.

Usage (dry run by default -- shows what would be deleted, changes nothing):
    cd forecast-backend
    python3 scripts/remove_synthetic_test_players.py

Actually delete them:
    python3 scripts/remove_synthetic_test_players.py --confirm
"""
from __future__ import annotations

import argparse
import sys

sys.path.insert(0, ".")

from sqlalchemy import or_  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.bot import BotProfile  # noqa: E402
from app.models.player import Player, Position  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.house_account import HOUSE_ACCOUNT_EMAIL  # noqa: E402

SYNTHETIC_PREFIXES = ("TestPro", "FixedPoolPro", "AuctionPro", "ThinLiquidityPro")


def _holder_labels(db: Session, player_id) -> list[str]:
    """Human-readable labels for whoever currently holds shares in this
    player -- purely for the dry-run report, so you can eyeball that
    these are test/bot holders and not something unexpected."""
    bot_user_ids = {r[0] for r in db.query(BotProfile.user_id).all()}
    house_row = db.query(User.id).filter(User.email == HOUSE_ACCOUNT_EMAIL).one_or_none()
    rows = (
        db.query(User.email, Position.quantity)
        .join(User, User.id == Position.user_id)
        .filter(Position.player_id == player_id, Position.quantity > 0)
        .all()
    )
    labels = []
    for email, qty in rows:
        tag = ""
        if house_row and email == house_row:
            tag = " [HOUSE]"
        elif email in bot_user_ids:
            tag = " [BOT]"
        labels.append(f"{email}{tag} ({qty} shares)")
    return labels


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--confirm", action="store_true", help="Actually delete the players found. Without this flag, it's a dry run.")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        candidates = (
            db.query(Player)
            .filter(or_(*[Player.gamertag.startswith(prefix) for prefix in SYNTHETIC_PREFIXES]))
            .all()
        )

        if not candidates:
            print("No synthetic test players found (matching prefixes: " + ", ".join(SYNTHETIC_PREFIXES) + "). Nothing to do.")
            return

        print(f"Found {len(candidates)} synthetic test player(s) to remove:")
        for p in candidates:
            holders = _holder_labels(db, p.id)
            holders_str = "; ".join(holders) if holders else "no current holders"
            print(f"  - id={p.id}  gamertag={p.gamertag!r}  held by: {holders_str}")

        if not args.confirm:
            print("\nDry run only -- nothing deleted. Re-run with --confirm to actually delete these players "
                  "(and their positions/orders/mappings via ON DELETE CASCADE).")
            return

        ids_to_delete = [p.id for p in candidates]
        deleted = db.query(Player).filter(Player.id.in_(ids_to_delete)).delete(synchronize_session=False)
        db.commit()
        print(f"\nDeleted {deleted} synthetic test player(s) and their cascaded positions/orders/mappings.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
