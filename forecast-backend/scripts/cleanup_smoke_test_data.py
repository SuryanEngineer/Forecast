#!/usr/bin/env python3
"""
Removes leftover smoke-test tournaments from a real database.

scripts/smoke_test.py is meant to run against a scratch/dev database (its
own docstring says so), but if it's ever accidentally run against the real
production DATABASE_URL, it leaves behind two real-looking Tournament rows
every time: "Smoke Test Cash Cup <run_id>" and "Fixed Pool Cash Cup
<run_id>" (plus whatever placement results / dividend payouts / Osirion
mappings got attached to them, and a handful of test users/players --
alice-<run_id>@test.local, TestPro<run_id>, etc.).

This script finds and removes just the tournaments (deleting a Tournament
row cascades automatically to its PlacementResult, DividendPayout,
OsirionTournamentMapping, and TournamentEntrant rows -- all declared
ondelete="CASCADE" in app/models/tournament.py) -- it does NOT touch the
leftover test users/players, since those have many more foreign-key
relationships (orders, trades, wallets, positions, auction bids...) that
haven't been individually audited for safe cascading; it only lists them
so you can decide.

Usage (dry run by default -- shows what would be deleted, deletes nothing):
    cd forecast-backend
    python3 scripts/cleanup_smoke_test_data.py

Actually delete the smoke-test tournaments found above:
    python3 scripts/cleanup_smoke_test_data.py --confirm
"""
from __future__ import annotations

import argparse
import sys

sys.path.insert(0, ".")

from app.db.session import SessionLocal  # noqa: E402
from app.models.player import Player  # noqa: E402
from app.models.tournament import Tournament  # noqa: E402
from app.models.user import User  # noqa: E402

TOURNAMENT_NAME_PATTERNS = ["Smoke Test Cash Cup %", "Fixed Pool Cash Cup %"]
TEST_USER_EMAIL_PATTERN = "%@test.local"
TEST_PLAYER_GAMERTAG_PATTERNS = ["TestPro%", "FixedPoolPro%", "AuctionPro%", "ThinLiquidityPro%"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm", action="store_true",
        help="Actually delete the tournaments found. Without this flag, it's a dry run that only prints what it found.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        tournaments: list[Tournament] = []
        for pattern in TOURNAMENT_NAME_PATTERNS:
            tournaments.extend(db.query(Tournament).filter(Tournament.name.like(pattern)).all())

        print(f"Found {len(tournaments)} smoke-test tournament(s):")
        for t in tournaments:
            print(f"  - {t.name!r}  (id={t.id}, type={t.tournament_type.value}, status={t.status.value})")

        users = db.query(User).filter(User.email.like(TEST_USER_EMAIL_PATTERN)).all()
        players: list[Player] = []
        for pattern in TEST_PLAYER_GAMERTAG_PATTERNS:
            players.extend(db.query(Player).filter(Player.gamertag.like(pattern)).all())

        if users or players:
            print(
                f"\nAlso found {len(users)} leftover smoke-test user(s) and {len(players)} leftover smoke-test "
                "player(s) -- NOT deleted by this script (they have more foreign-key relationships -- orders, "
                "trades, wallets, positions, auction bids -- that haven't been individually verified as safe to "
                "cascade). Listed here so you can review/remove them yourself if you want:"
            )
            for u in users:
                print(f"  user:   {u.email}")
            for p in players:
                print(f"  player: {p.gamertag}")

        if not tournaments:
            print("\nNothing to delete.")
            return

        if not args.confirm:
            print("\nDry run only -- nothing deleted. Re-run with --confirm to actually delete the tournaments listed above.")
            return

        for t in tournaments:
            db.delete(t)
        db.commit()
        print(f"\nDeleted {len(tournaments)} smoke-test tournament(s) (and everything that cascaded from them).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
