#!/usr/bin/env python3
"""
Removes the fake rows a unit-test run left in a REAL database.

What happened: a test file imported the app before the tests pointed it at their throwaway SQLite database, so tests that
create fixtures (tests/test_qualifier.py, tests/test_seasons.py) wrote them into the real database instead. They left:

  * tournaments named exactly "Cup" and "Solos Finals" (no Osirion mapping, no placements) -- the phantom "live" events
  * players whose gamertag looks like good_xxxxxx / bad_xxxxxx / sf_xxxxxx (six hex characters) and their qualifier rows
  * season-test data: a fake "Chapter 8: Season 2" and seasons wrongly closed by the test's fake clock

Dry run by default (changes nothing):
    cd forecast-backend
    python scripts/cleanup_test_run_data.py

Delete them and repair the seasons:
    python scripts/cleanup_test_run_data.py --confirm
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, ".")

from sqlalchemy import delete, func  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
import app.models  # noqa: E402,F401
from app.models.account import Season, SeasonEntry  # noqa: E402
from app.models.osirion import OsirionTournamentMapping  # noqa: E402
from app.models.player import Player  # noqa: E402
from app.models.tournament import PlacementResult, Tournament  # noqa: E402

FAKE_TOURNAMENTS = {"Cup", "Solos Finals"}
FAKE_PLAYER = re.compile(r"^(good|bad|sf)_[0-9a-f]{6}$")
TEST_ONLY_SEASONS = {"Chapter 8: Season 2"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm", action="store_true")
    args = ap.parse_args()
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        mapped = {r[0] for r in db.query(OsirionTournamentMapping.tournament_id).all()}
        placed = {r[0] for r in db.query(PlacementResult.tournament_id).distinct().all()}
        t_rows = [t for t in db.query(Tournament).filter(Tournament.name.in_(FAKE_TOURNAMENTS)).all() if t.id not in mapped and t.id not in placed]
        p_rows = [p for p in db.query(Player).all() if FAKE_PLAYER.match(p.gamertag or "")]

        print("Fake tournaments:")
        for t in t_rows:
            print(f"  {t.name!r} start {t.start_time} status {getattr(t.status, 'value', t.status)} (id {t.id})")
        print("Fake players:")
        for p in p_rows:
            print(f"  {p.gamertag}")

        seasons = db.query(Season).order_by(Season.starts_at.asc()).all()
        print("Seasons now:")
        for s in seasons:
            state = "ACTIVE" if s.is_active else ("finalized" if s.finalized_at else "scheduled")
            print(f"  {s.name:<34} {s.starts_at:%Y-%m-%d} -> {s.ends_at.strftime('%Y-%m-%d') if s.ends_at else 'TBD'} [{state}]")
        to_delete = [s for s in seasons if s.name in TEST_ONLY_SEASONS]
        # A season whose real window has not ended must not be closed: the test's fake clock closed some of them.
        to_reopen = [s for s in seasons if s.finalized_at is not None and s.name not in TEST_ONLY_SEASONS and (s.ends_at is None or s.ends_at > now)]
        for s in to_delete:
            print(f"  -> would DELETE test-only season {s.name!r}")
        for s in to_reopen:
            print(f"  -> would REOPEN {s.name!r} (its real end date has not passed)")

        if not args.confirm:
            print("\nDry run. Re-run with --confirm to apply.")
            return

        if t_rows:
            db.execute(delete(Tournament).where(Tournament.id.in_([t.id for t in t_rows])))
        if p_rows:
            db.execute(delete(Player).where(Player.id.in_([p.id for p in p_rows])))
        for s in to_delete:
            db.execute(delete(Season).where(Season.id == s.id))
        for s in to_reopen:
            s.finalized_at = None
            s.is_active = False
            for e in db.query(SeasonEntry).filter(SeasonEntry.season_id == s.id).all():
                e.final_value = e.final_points = e.final_rank = e.final_position = None
        db.flush()
        from app.services import season_calendar

        for line in season_calendar.sync_calendar(db) or ["seasons already match the calendar"]:
            print("  season:", line)
        db.commit()
        print("Done.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
