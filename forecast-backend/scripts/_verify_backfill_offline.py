"""One-time offline sanity check for the historical-backfill feature --
runs entirely against a throwaway local SQLite file with Osirion's API
mocked out, touches production nothing. Safe (and recommended) to run
once before trying backfill_historical_market.py against the real
database; safe to delete afterward, it's not meant to stick around as a
permanent part of the test suite.

Usage:
    cd forecast-backend
    python3 scripts/_verify_backfill_offline.py
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, ".")

db_fd, db_path = tempfile.mkstemp(suffix=".sqlite")
os.close(db_fd)
os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
os.environ["OSIRION_SYNC_ENABLED"] = "false"
os.environ["BOT_TRADING_ENABLED"] = "false"
os.environ["REDIS_ENABLED"] = "false"

from app.db.base import Base
from app.db.session import engine, SessionLocal
from app.models.dividend import DividendPayout
from app.models.player import Player
from app.models.tournament import PlacementResult, Tournament, TournamentResultArchive
from app.services import osirion_service

Base.metadata.create_all(bind=engine)

now = datetime.now(timezone.utc)
ended = now - timedelta(days=30)

FAKE_TOURNAMENT = {
    "eventId": "epicgames_TestHistoryCashCup",
    "eventGroup": "S1_CashCup",
    "regions": ["NAC"],
    "displayData": {"longFormatTitle": "History Cash Cup"},
    "eventWindows": [
        {
            "eventWindowId": "Window_Day1",
            "beginTime": (ended - timedelta(hours=3)).isoformat().replace("+00:00", "Z"),
            "endTime": ended.isoformat().replace("+00:00", "Z"),
            "round": 0,
            "scoreLocations": [
                {
                    "leaderboardEventId": "epicgames_TestHistoryCashCup",
                    "leaderboardEventWindowId": "Window_Day1",
                    "isMain": True,
                    "payoutTables": [
                        {
                            "scoringType": "rank",
                            "ranks": [
                                {"threshold": 1, "payouts": [{"rewardType": "ecomm", "value": "USD", "quantity": 1000}]},
                                {"threshold": 2, "payouts": [{"rewardType": "ecomm", "value": "USD", "quantity": 500}]},
                            ],
                        }
                    ],
                }
            ],
        }
    ],
}

FAKE_LEADERBOARD_PAGE = {
    "totalPages": 1,
    "entries": [
        {
            "rank": 1,
            "teamId": "team1",
            "pointsEarned": 50,
            "players": [{"accountId": "acct-1", "username": "HistoryPlayerOne"}],
        },
        {
            "rank": 2,
            "teamId": "team2",
            "pointsEarned": 40,
            "players": [{"accountId": "acct-2", "username": "HistoryPlayerTwo"}],
        },
    ],
}


def fake_list_tournaments(region=None, include_historic_data=False):
    return [FAKE_TOURNAMENT]


def fake_get_leaderboard_page(leaderboard_event_id, leaderboard_event_window_id, page=0):
    return FAKE_LEADERBOARD_PAGE


db = SessionLocal()
try:
    with mock.patch("app.services.osirion_service.osirion_client.list_tournaments", side_effect=fake_list_tournaments), \
         mock.patch("app.services.osirion_service.osirion_client.get_leaderboard_page", side_effect=fake_get_leaderboard_page):

        scan = osirion_service.find_historical_backfill_candidates(db)
        assert not scan.errors, f"scan errors: {scan.errors}"
        assert scan.events_seen == 1, f"expected 1 event seen, got {scan.events_seen}"
        assert len(scan.candidates) == 1, f"expected 1 candidate, got {len(scan.candidates)}: {scan.candidates}"
        candidate = scan.candidates[0]
        assert candidate.tournament_type.value == "cash_cup", candidate.tournament_type
        print("PASS: scan found exactly 1 eligible historical candidate, classified as cash_cup")

        result = osirion_service.backfill_historical_tournaments(db, scan.candidates)
        assert not result.errors, f"backfill errors: {result.errors}"
        assert result.tracked == 1, f"expected 1 tracked, got {result.tracked}"
        assert result.total_matched == 2, f"expected 2 matched, got {result.total_matched}"
        print("PASS: backfill tracked 1 tournament, matched 2 players")

    tournaments = db.query(Tournament).all()
    assert len(tournaments) == 1, f"expected 1 tournament row, got {len(tournaments)}"
    t = tournaments[0]
    assert t.is_historical_archive is True, "tournament not marked is_historical_archive"
    assert t.status.value == "finalized", f"expected finalized status, got {t.status.value}"
    print("PASS: tournament marked is_historical_archive=True and status=FINALIZED")

    placements = db.query(PlacementResult).filter(PlacementResult.tournament_id == t.id).all()
    assert len(placements) == 2, f"expected 2 placement results, got {len(placements)}"
    print("PASS: 2 PlacementResult rows created")

    players = db.query(Player).all()
    assert len(players) == 2, f"expected 2 players created, got {len(players)}"
    print("PASS: 2 real Player stocks created")

    payouts = db.query(DividendPayout).all()
    assert len(payouts) == 0, f"expected ZERO dividend payouts, got {len(payouts)}"
    print("PASS: zero DividendPayout rows created (no exploit path)")

    archive = db.query(TournamentResultArchive).filter_by(tournament_id=t.id).one_or_none()
    assert archive is not None and archive.raw_leaderboard_entries, "expected raw leaderboard archived"
    print("PASS: raw leaderboard archived in TournamentResultArchive")

    # Simulate the public list_tournaments endpoint's filter
    visible = db.query(Tournament).filter(Tournament.is_historical_archive.is_(False)).all()
    assert len(visible) == 0, f"expected historical tournament excluded from public list, got {len(visible)}"
    print("PASS: historical tournament correctly excluded from public /tournaments list filter")

    # Simulate the player-history endpoint (unfiltered by is_historical_archive)
    history_count = db.query(PlacementResult).filter(PlacementResult.player_id == placements[0].player_id).count()
    assert history_count == 1
    print("PASS: player history endpoint would still show the backfilled placement")

    # Re-run scan to confirm idempotency (already-tracked window is skipped)
    with mock.patch("app.services.osirion_service.osirion_client.list_tournaments", side_effect=fake_list_tournaments), \
         mock.patch("app.services.osirion_service.osirion_client.get_leaderboard_page", side_effect=fake_get_leaderboard_page):
        scan2 = osirion_service.find_historical_backfill_candidates(db)
        assert len(scan2.candidates) == 0, f"expected 0 candidates on second scan, got {len(scan2.candidates)}"
        assert scan2.already_tracked == 1
    print("PASS: re-running the scan correctly finds nothing new (idempotent)")

    print("\nALL CHECKS PASSED")
finally:
    db.close()
    os.remove(db_path)
