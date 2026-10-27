"""Fortnite season calendar: sync, activation, rollover (incl. an open-ended season), on a throwaway SQLite DB."""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TMP = tempfile.mkdtemp(prefix="forecast_seasons_")
os.environ.update({
    "FORECAST_ENV_FILE": os.path.join(_TMP, "none.env"), "DATABASE_URL": f"sqlite:///{os.path.join(_TMP, 't.db')}",
    "REDIS_ENABLED": "false", "BOT_TRADING_ENABLED": "false", "OSIRION_SYNC_ENABLED": "false",
})


def at(y, m, d, hh=0):
    return datetime(y, m, d, hh, tzinfo=timezone.utc)


class SeasonCalendar(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app.db.base import Base
        from app.db.session import SessionLocal, engine
        import app.models  # noqa: F401
        Base.metadata.create_all(bind=engine)
        cls.db = SessionLocal()

    def _now(self, when):
        from app.services import season_service
        season_service._now = lambda: when

    def test_full_timeline(self):
        from app.models.account import Season
        from app.services import season_calendar, season_service
        db = self.db
        self._now(at(2026, 10, 26))
        acts = season_calendar.sync_calendar(db)
        db.commit()
        self.assertEqual(db.query(Season).count(), 3)
        self.assertTrue(any("created" in a for a in acts))
        cur, nxt = season_service.current_and_next(db)
        self.assertEqual(cur.name, "Chapter 7: Season 4 (Override)")
        self.assertEqual(nxt.name, "Mini-Season (Treasure Hunters)")
        self.assertEqual(db.query(Season).filter(Season.is_active.is_(True)).count(), 1)

        # idempotent
        self.assertEqual([a for a in season_calendar.sync_calendar(db) if "created" in a or "updated" in a], [])

        # Nov 1: override season closes, mini-season opens
        self._now(at(2026, 11, 1, 1))
        season_service.run_rollover(db); db.commit()
        cur, nxt = season_service.current_and_next(db)
        self.assertEqual(cur.name, "Mini-Season (Treasure Hunters)")
        self.assertEqual(cur.kind, "mini")
        self.assertIsNotNone(db.query(Season).filter(Season.name == "Chapter 7: Season 4 (Override)").one().finalized_at)

        # Dec 5: chapter 8 opens with an open end date and stays active indefinitely
        self._now(at(2026, 12, 6))
        season_service.run_rollover(db); db.commit()
        cur, nxt = season_service.current_and_next(db)
        self.assertEqual(cur.name, "Chapter 8: Season 1")
        self.assertIsNone(cur.ends_at)
        self.assertIsNone(nxt)
        self._now(at(2027, 6, 1))
        self.assertEqual(season_service.run_rollover(db), [])
        self.assertEqual(season_service.get_active_season(db).name, "Chapter 8: Season 1")

        # A later season starting closes the TBD one even though no end was ever set
        season_service.create_season(db, "Chapter 8: Season 2", at(2027, 3, 1), None)
        db.commit()
        season_service.run_rollover(db); db.commit()
        self.assertEqual(season_service.get_active_season(db).name, "Chapter 8: Season 2")
        self.assertIsNotNone(db.query(Season).filter(Season.name == "Chapter 8: Season 1").one().finalized_at)


if __name__ == "__main__":
    unittest.main()
