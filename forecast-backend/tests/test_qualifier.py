"""Qualifier maths, advancement-cutoff parsing, and the qualifier -> bot-outlook model (throwaway SQLite)."""
import os
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TMP = tempfile.mkdtemp(prefix="forecast_qual_")
os.environ.update({
    "FORECAST_ENV_FILE": os.path.join(_TMP, "none.env"), "DATABASE_URL": f"sqlite:///{os.path.join(_TMP, 't.db')}",
    "REDIS_ENABLED": "false", "BOT_TRADING_ENABLED": "false", "OSIRION_SYNC_ENABLED": "false",
})

from app.engine import qualifier_math as qm  # noqa: E402


class QualifierMath(unittest.TestCase):
    def test_qual_score_bounds_and_order(self):
        self.assertEqual(qm.qual_score(1, 50000), 1.0)
        self.assertGreater(qm.qual_score(100, 50000), qm.qual_score(5000, 50000))
        self.assertTrue(0.0 <= qm.qual_score(10**6, 50000) <= 1.0)

    def test_fit_line_recovers_slope_and_shrinks_with_little_data(self):
        pairs = [(q / 100, 0.1 + 0.7 * q / 100) for q in range(0, 100, 2)] * 4
        a, b, sd, n = qm.fit_line(pairs)
        self.assertAlmostEqual(b, 0.7, delta=0.1)
        a0, b0, _sd, n0 = qm.fit_line([])
        self.assertEqual((a0, b0, n0), (0.30, 0.45, 0))

    def test_p_qualify_monotonic(self):
        rates = qm.qualify_rates([])
        vals = [qm.p_qualify(q / 10, rates) for q in range(11)]
        self.assertEqual(vals, sorted(vals))

    def test_expected_strength_uses_team_prior(self):
        weak = qm.expected_strength(0.3, 0.45, 0.5, 0.2, 2)
        strong = qm.expected_strength(0.3, 0.45, 0.5, 0.9, 2)
        self.assertGreater(strong, weak)

    def test_placement_roundtrip(self):
        for plc in (1, 10, 50, 100):
            self.assertAlmostEqual(qm.placement_from_strength(qm.final_strength(plc, 100), 100), plc, delta=1)


class AdvanceCutoff(unittest.TestCase):
    def test_parse(self):
        from app.services.qualifier_service import parse_advance_cutoff
        raw = {"scoreLocations": [{"leaderboardEventWindowId": "W1", "payoutTables": [{"scoringType": "rank", "ranks": [
            {"threshold": 1000, "payouts": [{"rewardType": "token", "rewardMode": "standard", "value": "Cup_Final", "quantity": 1}]},
            {"threshold": 2500, "payouts": [{"rewardType": "token", "rewardMode": "standard", "value": "Cup_Final", "quantity": 1}]},
            {"threshold": 9999, "payouts": [{"rewardType": "token", "rewardMode": "standard", "value": "Deny_X", "quantity": 1}]},
            {"threshold": 5, "payouts": [{"rewardType": "currency", "value": "usd", "quantity": 100}]},
        ]}]}, {"leaderboardEventWindowId": "OTHER", "payoutTables": []}]}
        self.assertEqual(parse_advance_cutoff(raw, "W1"), 2500)
        self.assertIsNone(parse_advance_cutoff(raw, "OTHER"))
        self.assertIsNone(parse_advance_cutoff({}, "W1"))


class QualifierViews(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app.db.base import Base
        from app.db.session import SessionLocal, engine
        import app.models  # noqa: F401
        Base.metadata.create_all(bind=engine)
        cls.db = SessionLocal()

    def test_views(self):
        from app.models.player import Player
        from app.models.qualifier import QualifierResult, QualifierWindow
        from app.models.tournament import Tournament, TournamentStatus, TournamentType
        from app.services import qualifier_model_service as qms
        db = self.db
        now = datetime.now(timezone.utc)
        t = Tournament(name="Cup", tournament_type=TournamentType.CASH_CUP, start_time=now + timedelta(days=1), status=TournamentStatus.SCHEDULED)
        db.add(t)
        mk = lambda n: Player(gamertag=n, ipo_price=10, total_shares_outstanding=1000)  # noqa: E731
        good, bad = mk("good_" + uuid.uuid4().hex[:6]), mk("bad_" + uuid.uuid4().hex[:6])
        db.add_all([good, bad]); db.flush()
        w = QualifierWindow(tournament_id=t.id, osirion_event_id="e", event_window_id="w", leaderboard_event_id="le",
                            leaderboard_event_window_id="lw", stage_index=1, field_estimate=10000, advance_cutoff=1000,
                            is_complete=True, begin_time=now - timedelta(days=2), end_time=now - timedelta(days=1))
        db.add(w); db.flush()
        db.add_all([
            QualifierResult(window_id=w.id, tournament_id=t.id, player_id=good.id, rank=20, team_id="a", team_size=2, teammate_player_ids=[str(bad.id)]),
            QualifierResult(window_id=w.id, tournament_id=t.id, player_id=bad.id, rank=4000, team_id="b", team_size=1, teammate_player_ids=[]),
        ])
        db.commit()
        qms.clear_cache()
        views = qms.build_views(db, [good.id, bad.id], {good.id: 0.05, bad.id: 0.05}, {good.id: 0.6, bad.id: 0.4})
        self.assertIn(good.id, views); self.assertIn(bad.id, views)
        self.assertGreater(views[good.id].perf_ratio, views[bad.id].perf_ratio)
        self.assertEqual(views[bad.id].status, "eliminated")
        self.assertEqual(views[good.id].status, "likely")
        self.assertIn(bad.id, views[good.id].teammates)

    def test_same_field_earlier_day_is_not_an_elimination_risk(self):
        """Day 1 of a 2-day Finals (no advancement cutoff, ~100 players) must not mark weak day-1 players as unlikely."""
        from app.models.player import Player
        from app.models.qualifier import QualifierResult, QualifierWindow
        from app.models.tournament import Tournament, TournamentStatus, TournamentType
        from app.services import qualifier_model_service as qms
        db = self.db
        now = datetime.now(timezone.utc)
        t = Tournament(name="Solos Finals", tournament_type=TournamentType.FNCS_FINALS, start_time=now + timedelta(hours=10), status=TournamentStatus.SCHEDULED)
        db.add(t)
        p = Player(gamertag="sf_" + uuid.uuid4().hex[:6], ipo_price=10, total_shares_outstanding=1000)
        db.add(p); db.flush()
        w = QualifierWindow(tournament_id=t.id, osirion_event_id="e2", event_window_id="w2", leaderboard_event_id="le2",
                            leaderboard_event_window_id="lw2", stage_index=1, field_estimate=100, advance_cutoff=None,
                            is_complete=True, begin_time=now - timedelta(days=1), end_time=now - timedelta(hours=12))
        db.add(w); db.flush()
        db.add(QualifierResult(window_id=w.id, tournament_id=t.id, player_id=p.id, rank=95, team_id="x", team_size=1, teammate_player_ids=[]))
        db.commit()
        qms.clear_cache()
        v = qms.build_views(db, [p.id], {p.id: 0.05}, {p.id: 0.5})[p.id]
        self.assertEqual(v.status, "likely")
        self.assertGreaterEqual(v.p_qualify, 0.95)

    def test_same_field_helper(self):
        from types import SimpleNamespace as NS
        from app.services.qualifier_model_service import _same_field
        self.assertTrue(_same_field([NS(stage_index=1, advance_cutoff=None, field_estimate=100)]))
        self.assertFalse(_same_field([NS(stage_index=1, advance_cutoff=50, field_estimate=100)]))
        self.assertFalse(_same_field([NS(stage_index=1, advance_cutoff=None, field_estimate=5000)]))
        self.assertFalse(_same_field([]))


if __name__ == "__main__":
    unittest.main()
