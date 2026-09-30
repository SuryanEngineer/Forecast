#!/usr/bin/env python3
"""
Read-only deep-dive into "why is the Markets page empty/not loading".
Prints every fact needed to tell apart the possible causes:

  1. A connection/config problem (wrong DATABASE_URL, wrong password,
     env vars not actually picked up) -- this script itself would fail
     to even connect, with a clear error, instead of printing zeros.
  2. Zero Player rows exist at all -- nothing has ever been IPO'd,
     because no tracked tournament has produced any real leaderboard
     data yet (or Osirion syncing has been off).
  3. Player rows DO exist, but list_market_snapshots()/the /markets
     endpoint aren't returning them for some other reason -- this
     script calls that exact function directly, the same one the API
     route calls, so if this script sees players but the API doesn't,
     the bug is in the API layer (or something about how the running
     server process was started), not the data.

Usage:
    cd forecast-backend
    python3 scripts/diagnose_market.py
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from app.core.config import settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.osirion import OsirionPlayerMapping, OsirionTournamentMapping  # noqa: E402
from app.models.player import Player  # noqa: E402
from app.models.tournament import PlacementResult, Tournament, TournamentStatus  # noqa: E402
from app.services import market_data_service  # noqa: E402


def _mask(url: str) -> str:
    # Show enough to tell hosts/users apart without printing the password.
    if "@" not in url:
        return url
    creds, rest = url.rsplit("@", 1)
    scheme_user = creds.split(":")
    if len(scheme_user) >= 2:
        return f"{scheme_user[0]}:***@{rest}"
    return f"***@{rest}"


def main() -> None:
    print("=== Config ===")
    print(f"DATABASE_URL (masked): {_mask(settings.DATABASE_URL)}")
    print(f"DEMO_MODE: {settings.DEMO_MODE}")
    print(f"BOT_TRADING_ENABLED: {settings.BOT_TRADING_ENABLED}")
    print(f"OSIRION_SYNC_ENABLED: {settings.OSIRION_SYNC_ENABLED}")
    print(f"OSIRION_AUTO_TRACK_ENABLED: {settings.OSIRION_AUTO_TRACK_ENABLED}")
    print()

    db = SessionLocal()
    try:
        print("=== Connectivity ===")
        # If DATABASE_URL/credentials are wrong, this next line raises --
        # and you'll see a clear connection error instead of the report
        # below, which itself is useful information.
        db.execute(Player.__table__.select().limit(1))
        print("Connected OK.")
        print()

        print("=== Players ===")
        total_players = db.query(Player).count()
        active_players = db.query(Player).filter(Player.is_active.is_(True)).count()
        print(f"Total Player rows: {total_players}")
        print(f"Active (is_active=True) Player rows: {active_players}")
        if total_players > 0:
            sample = db.query(Player).order_by(Player.created_at.desc()).limit(10).all()
            print("Most recently created players:")
            for p in sample:
                print(f"  - {p.gamertag!r}  active={p.is_active}  ipo_price={p.ipo_price}  created_at={p.created_at}")
        print()

        print("=== Tournaments ===")
        total_tournaments = db.query(Tournament).count()
        by_status = {}
        for status_value in TournamentStatus:
            by_status[status_value.value] = db.query(Tournament).filter(Tournament.status == status_value).count()
        historical = db.query(Tournament).filter(Tournament.is_historical_archive.is_(True)).count()
        print(f"Total Tournament rows: {total_tournaments}")
        print(f"By status: {by_status}")
        print(f"is_historical_archive=True: {historical}")
        print()

        print("=== Osirion tracking/sync state ===")
        total_mappings = db.query(OsirionTournamentMapping).count()
        synced_mappings = db.query(OsirionTournamentMapping).filter(OsirionTournamentMapping.last_synced_at.isnot(None)).count()
        complete_mappings = db.query(OsirionTournamentMapping).filter(OsirionTournamentMapping.last_sync_complete.is_(True)).count()
        print(f"Total tracked (OsirionTournamentMapping) rows: {total_mappings}")
        print(f"...with at least one sync attempt (last_synced_at set): {synced_mappings}")
        print(f"...that fully completed a leaderboard walk (last_sync_complete=True): {complete_mappings}")
        print()

        print("=== Placement results (the thing that actually creates/IPOs players) ===")
        total_placements = db.query(PlacementResult).count()
        distinct_players_with_placements = db.query(PlacementResult.player_id).distinct().count()
        print(f"Total PlacementResult rows: {total_placements}")
        print(f"Distinct players with at least one placement: {distinct_players_with_placements}")
        print()

        print("=== Osirion account-id mappings (dedup cache) ===")
        total_account_mappings = db.query(OsirionPlayerMapping).count()
        print(f"Total OsirionPlayerMapping rows: {total_account_mappings}")
        print()

        print("=== Calling market_data_service.list_market_snapshots() directly (same function the API uses) ===")
        snapshots = market_data_service.list_market_snapshots(db)
        print(f"Returned {len(snapshots)} snapshot(s).")
        for s in snapshots[:10]:
            print(f"  - {s['gamertag']!r}  last_price={s['last_price']}  market_cap={s['market_cap']}")

        print()
        print("=== Verdict ===")
        if total_players == 0:
            print(
                "No Player rows exist at all. Nothing has ever IPO'd -- this means no tracked tournament has ever "
                "produced a single matched leaderboard entry. Check the 'Osirion tracking/sync state' section above: "
                "if total tracked mappings is 0, no tournament has ever been auto-tracked/synced at all. If it's >0 "
                "but synced_mappings is 0, tracking exists but syncing has never actually run (check "
                "OSIRION_SYNC_ENABLED above, and whether uvicorn's background loop has been running long enough -- "
                "every ~45s per app/core/config.py's OSIRION_SYNC_INTERVAL_SECONDS)."
            )
        elif active_players == 0:
            print(
                f"{total_players} Player row(s) exist but NONE are active (is_active=True) -- something has been "
                "deactivating players. This would need a direct look at whatever code path flips is_active to False."
            )
        elif len(snapshots) == 0:
            print(
                f"{active_players} active player(s) exist, but list_market_snapshots() returned 0 -- this would be "
                "a genuine bug in that function or its query, not a data problem. Please share this full output."
            )
        else:
            print(
                f"{len(snapshots)} snapshot(s) came back correctly from the exact function the API uses. If the "
                "Markets PAGE still shows nothing, the problem is downstream of this -- almost certainly the running "
                "uvicorn process itself (e.g. it started with a different/broken DATABASE_URL baked in from before "
                "the .env fix, and needs a full stop + restart, not just --reload's auto-reload) or the browser "
                "still pointed at a different backend. Fully stop uvicorn (Ctrl+C, not just letting --reload pick up "
                "a file change) and start it fresh, then hard-refresh the Markets page."
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()
