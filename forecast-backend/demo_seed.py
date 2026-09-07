"""
One-command bootstrap for DEMO MODE. Creates a fresh local SQLite
database (if it doesn't exist yet), seeds a static roster of players
(app/data/demo_players.json) with starting House liquidity, seeds the
bot trading population, and creates a demo admin login -- everything a
visitor needs to open the app, register their own account, and start
trading immediately, with zero external services (no Postgres, no
Redis, no cloud accounts).

Usage (from forecast-backend/, with the venv active):
    python demo_seed.py            # create/top-up the demo database
    python demo_seed.py --fresh    # wipe demo.db and start completely clean

Safe to re-run: seeding is idempotent (existing players/bots/admin are
left alone, only what's missing gets created). This script refuses to
run against anything that isn't DEMO_MODE, specifically so it can never
be pointed at the real production database by accident (see the
DEMO_MODE.md safety note).

See DEMO_MODE.md for the full picture of how demo mode differs from the
real product.
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

# Default to the demo env file unless the caller already set one --
# lets `python demo_seed.py` just work without remembering to export
# FORECAST_ENV_FILE first, while still respecting an explicit override.
os.environ.setdefault("FORECAST_ENV_FILE", ".env.demo")

from app.core.config import settings  # noqa: E402  (must come after the env var default above)

if not settings.DEMO_MODE:
    print(
        "Refusing to run: DEMO_MODE is not enabled for the currently-loaded "
        f"settings (FORECAST_ENV_FILE={os.environ.get('FORECAST_ENV_FILE')!r}, "
        f"DATABASE_URL={settings.DATABASE_URL!r}).\n"
        "This script seeds fake players, fake bots, and a demo admin login -- "
        "it must never run against the real database. Set FORECAST_ENV_FILE=.env.demo "
        "(or fix .env.demo so DEMO_MODE=true) and try again.",
        file=sys.stderr,
    )
    sys.exit(1)

if "--fresh" in sys.argv and settings.DATABASE_URL.startswith("sqlite"):
    db_path = settings.DATABASE_URL.split("sqlite:///", 1)[-1]
    path = Path(db_path)
    if path.exists():
        path.unlink()
        print(f"Deleted existing demo database at {path}")

import random  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models.player import Player  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402
from app.services import bot_trading_service, economic_params_service, market_maker_service, player_service, wallet_service  # noqa: E402

DEMO_ADMIN_EMAIL = "demo-admin@forecast.local"
DEMO_ADMIN_PASSWORD = "demo1234"
DEMO_ADMIN_DISPLAY_NAME = "Demo Admin"

DATA_FILE = Path(__file__).parent / "app" / "data" / "demo_players.json"


def seed_players(db) -> tuple[int, int]:
    data = json.loads(DATA_FILE.read_text())
    created, skipped = 0, 0
    for entry in data["players"]:
        existing = db.query(Player).filter(Player.gamertag == entry["gamertag"]).one_or_none()
        if existing is not None:
            skipped += 1
            continue
        player = player_service.create_player(
            db,
            gamertag=entry["gamertag"],
            real_name=entry.get("real_name"),
            team=entry.get("team"),
            region=entry.get("region"),
            power_rating=entry.get("power_rating", 65),
        )
        market_maker_service.post_bot_quotes(db, player)
        created += 1
    db.commit()
    return created, skipped


def seed_bots(db) -> int:
    target = int(economic_params_service.get_param(db, "bots.population_size"))
    db.commit()
    created = bot_trading_service.ensure_bot_population(db, target, random.Random())
    db.commit()
    return created


def seed_demo_admin(db) -> bool:
    existing = db.query(User).filter(User.email == DEMO_ADMIN_EMAIL).one_or_none()
    if existing is not None:
        return False

    admin = User(
        id=uuid.uuid4(),
        email=DEMO_ADMIN_EMAIL,
        password_hash=hash_password(DEMO_ADMIN_PASSWORD),
        display_name=DEMO_ADMIN_DISPLAY_NAME,
        role=UserRole.ADMIN,
        is_active=True,
    )
    db.add(admin)
    db.flush()
    wallet_service.get_or_create_wallet(db, admin.id)
    starting_balance = economic_params_service.get_param(db, "wallet.starting_balance")
    if starting_balance > 0:
        wallet_service.deposit(db, admin.id, starting_balance, memo="Demo admin starting balance")
    db.commit()
    return True


def main() -> None:
    print(f"Demo mode confirmed. DATABASE_URL={settings.DATABASE_URL}")

    Base.metadata.create_all(bind=engine)
    print("Schema ready (created any missing tables).")

    db = SessionLocal()
    try:
        created_players, skipped_players = seed_players(db)
        print(f"Players: {created_players} created, {skipped_players} already existed.")

        created_bots = seed_bots(db)
        print(f"Bots: {created_bots} created (population topped up to target).")

        admin_created = seed_demo_admin(db)
        print(f"Demo admin: {'created' if admin_created else 'already existed'}.")
    finally:
        db.close()

    print()
    print("Demo database ready. Next steps:")
    print("  1. Start the demo backend:")
    print("       FORECAST_ENV_FILE=.env.demo uvicorn app.main:app --reload --port 8001")
    print("     (Windows PowerShell: $env:FORECAST_ENV_FILE=\".env.demo\"; uvicorn app.main:app --reload --port 8001)")
    print(f"  2. Log in as the demo admin ({DEMO_ADMIN_EMAIL} / {DEMO_ADMIN_PASSWORD}) or register a brand new account --")
    print("     either way it's a real account in the local demo.db, unconnected to the real product's database.")
    print("  3. Bots and randomized tournaments start running automatically once the server is up.")


if __name__ == "__main__":
    main()
