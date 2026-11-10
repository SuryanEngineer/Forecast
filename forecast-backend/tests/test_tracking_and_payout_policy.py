"""Tracking policy + top-N payout policy (pure functions). Run: python3 -m unittest discover -s tests -v"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.engine import completion as comp, format_policy as fp, payout_policy, tracking_policy as tp
from app.engine.dividend_calculator import DEFAULT_PLACEMENT_CURVE, placement_payout_fraction


class TestReloadRole(unittest.TestCase):
    def test_roles(self):
        r = tp.reload_family_role
        self.assertEqual(r("FNCS Solo Reload Finals"), tp.ROLE_FINAL)
        self.assertEqual(r("S41_FNCS_SoloReload_Finals"), tp.ROLE_FINAL)
        self.assertEqual(r("FNCS Solo Reload Heats — Session 1"), tp.ROLE_QUALIFIER)
        self.assertEqual(r("FNCS Reload Last Chance Qualifier Session 2"), tp.ROLE_QUALIFIER)
        self.assertEqual(r("FNCS Solo Reload Semifinals"), tp.ROLE_QUALIFIER)
        self.assertEqual(r("FNCS Solo Reload Open Heat"), tp.ROLE_OPEN)
        self.assertEqual(r("FNCS Solo Reload Open Round 1"), tp.ROLE_OPEN)

    def test_not_family(self):
        self.assertIsNone(tp.reload_family_role("Arenas Cash Cup"))
        self.assertIsNone(tp.reload_family_role("Reload Cash Cup"))
        self.assertIsNone(tp.reload_family_role("FNCS Global Championship Finals"))
        self.assertIsNone(tp.reload_family_role(None))

    def test_region(self):
        allowed = {"NAC", "EU"}
        self.assertTrue(tp.reload_region_ok([], allowed))
        self.assertTrue(tp.reload_region_ok(["NAC", "BR"], allowed))
        self.assertFalse(tp.reload_region_ok(["OCE"], allowed))


class TestSeries(unittest.TestCase):
    def test_series_and_exclusions(self):
        self.assertEqual(tp.series_key("Season42_ArenaTestCup epicgames_S42_ArenaTestCup_NAC Arenas Test Cup"), "arena")
        self.assertEqual(tp.series_key("Season42_ArenaCashCup"), "arena")
        self.assertEqual(tp.series_key("S41_TriosCashCup"), "trio")
        self.assertIsNone(tp.series_key("Season42_Something"))
        self.assertTrue(tp.is_excluded_family("Mobile Reload (Elite Stronghold) Victory Cup"))
        self.assertTrue(tp.is_excluded_family("Season41_SkinCup"))
        self.assertFalse(tp.is_excluded_family("Arenas Test Cup"))


class TestSetLobby(unittest.TestCase):
    def test_verdicts(self):
        v = tp.verdict_from_field
        self.assertIsNone(v(None, None, None))
        self.assertIsNone(v(0, 1, 0))
        self.assertTrue(v(100, 1, 100))
        self.assertTrue(v(250, 1, 250))
        self.assertFalse(v(251, 1, 251))
        self.assertFalse(v(100, 500, 100))  # many pages: an open field
        self.assertTrue(v(100, 2, 100))  # 101 teams total at most


class TestClusters(unittest.TestCase):
    def test_gap(self):
        t0 = datetime(2026, 11, 1, 18, tzinfo=timezone.utc)

        class W:
            def __init__(self, begin, hours=3):
                self.begin_time, self.end_time = begin, begin + timedelta(hours=hours)

        day1, day2 = W(t0), W(t0 + timedelta(days=1))
        next_week = W(t0 + timedelta(days=7))
        clusters = tp.cluster_by_gap([next_week, day2, day1], lambda w: w.begin_time, lambda w: w.end_time)
        self.assertEqual([len(c) for c in clusters], [2, 1])


class TestPayoutPolicy(unittest.TestCase):
    def test_paid_places(self):
        self.assertEqual(payout_policy.paid_places("[NAC] Arenas Cash Cup — Nov 14, 2026"), 10)
        self.assertIsNone(payout_policy.paid_places("FNCS Solo Reload Finals"))
        self.assertIsNone(payout_policy.paid_places(None))

    def test_top10_curve_sums_to_one_and_cuts_tail(self):
        curve = payout_policy.curve_for(dict(DEFAULT_PLACEMENT_CURVE), "Arenas Cash Cup")
        self.assertEqual(sorted(curve), list(range(1, 11)))
        self.assertEqual(sum(curve.values()), D("1"))
        pool = D("300000")
        paid = sum(pool * placement_payout_fraction(p, 100, curve) for p in range(1, 101))
        self.assertLessEqual(abs(paid - pool), D("1"))
        self.assertEqual(placement_payout_fraction(11, 100, curve), 0)
        self.assertEqual(placement_payout_fraction(100, 100, curve), 0)
        self.assertGreater(placement_payout_fraction(10, 100, curve), 0)

    def test_other_events_use_global_curve(self):
        base = dict(DEFAULT_PLACEMENT_CURVE)
        self.assertEqual(payout_policy.curve_for(base, "FNCS Solo Reload Finals"), base)


class TestFormatPolicy(unittest.TestCase):
    def test_decide_rules(self):
        d = fp.decide
        # open round
        self.assertIsNone(d(lobby="open", has_cash=False, stage_index=0))
        self.assertEqual(d(lobby="open", has_cash=True, stage_index=0)["pool_param"], fp.POOL_ROUND)  # $150k
        # set lobby
        self.assertEqual(d(lobby="set", has_cash=True, stage_index=2)["pool_param"], fp.POOL_FINAL)   # $300k final
        self.assertEqual(d(lobby="set", has_cash=True, stage_index=2)["stage"], "final")
        self.assertIsNone(d(lobby="set", has_cash=False, stage_index=0))                               # 1st round, no cash
        later = d(lobby="set", has_cash=False, stage_index=1)
        self.assertEqual(later["pool_param"], fp.POOL_ROUND)                                           # later round $150k
        self.assertFalse(later["cash"])
        # field not visible yet: cautious pool, flagged provisional
        unk = d(lobby="unknown", has_cash=True, stage_index=0)
        self.assertTrue(unk["provisional"])
        self.assertEqual(unk["pool_param"], fp.POOL_ROUND)
        self.assertIsNone(d(lobby="unknown", has_cash=False, stage_index=0))

    def test_tier_record_keeps_tier_pool(self):
        self.assertIsNone(fp.tier_record(lobby="set", has_cash=True)["pool_param"])

    def test_scoring_kind(self):
        def sl(*rules):
            return {"scoringRules": list(rules)}
        win_only = sl({"trackedStat": "PLACEMENT_STAT_INDEX", "rewardTiers": [{"keyValue": 1, "pointsEarned": 1}]})
        self.assertEqual(fp.scoring_kind(win_only), "wins")
        placement = sl({"trackedStat": "PLACEMENT_STAT_INDEX", "rewardTiers": [{"keyValue": 1, "pointsEarned": 3}, {"keyValue": 5, "pointsEarned": 2}]})
        self.assertEqual(fp.scoring_kind(placement), "placement")
        elims = sl({"trackedStat": "TEAM_ELIMS_STAT_INDEX", "rewardTiers": [{"keyValue": 1, "pointsEarned": 1}]},
                   {"trackedStat": "PLACEMENT_STAT_INDEX", "rewardTiers": [{"keyValue": 1, "pointsEarned": 1}]})
        self.assertEqual(fp.scoring_kind(elims), "placement")
        self.assertEqual(fp.scoring_kind({}), "placement")
        self.assertEqual(fp.scoring_kind(None), "placement")

    def test_paid_places_from_rules(self):
        self.assertEqual(payout_policy.paid_places_for("Some Cup", {"paid_places": 25}), 25)
        self.assertEqual(payout_policy.paid_places_for("Arenas Cash Cup", {"paid_places": 7}), 7)  # the event's own table wins
        self.assertEqual(payout_policy.paid_places_for("Arenas Cash Cup", {}), 10)  # by-name rule is the fallback
        self.assertEqual(payout_policy.paid_places_for("Arenas Cash Cup", None), 10)
        self.assertIsNone(payout_policy.paid_places_for("Some Cup", {}))
        curve = payout_policy.curve_for_rules(dict(DEFAULT_PLACEMENT_CURVE), "Some Cup", {"paid_places": 25})
        self.assertEqual(sorted(curve), list(range(1, 26)))
        self.assertEqual(sum(curve.values()), D("1"))

    def test_describe(self):
        self.assertIn("open lobby", fp.describe({"lobby": "open", "stage": "round", "cash": True, "scoring": "placement"}))


def _sess(sid, end, place):
    return {"sessionId": sid, "endTime": end, "trackedStats": {"PLACEMENT_STAT_INDEX": place}}


class TestCompletion(unittest.TestCase):
    T0 = datetime(2026, 11, 14, 19, 0, tzinfo=timezone.utc)

    def at(self, minutes):
        return (self.T0 + timedelta(minutes=minutes)).isoformat()

    def entries(self, games_with_winner, games_total=None):
        """Two teams; game g is won by team A when g <= games_with_winner (otherwise nobody has placement 1 yet)."""
        total = games_total or games_with_winner
        a, b = [], []
        for g in range(1, total + 1):
            won = g <= games_with_winner
            a.append(_sess(f"g{g}", self.at(g * 20), 1 if won else 2))
            b.append(_sess(f"g{g}", self.at(g * 20), 2 if won else 3))
        return [{"sessionHistory": a}, {"sessionHistory": b}]

    def test_progress(self):
        p = comp.analyze_games(self.entries(3))
        self.assertEqual((p.games_seen, p.games_done), (3, 3))
        self.assertEqual(p.last_game_end, self.T0 + timedelta(minutes=60))
        p = comp.analyze_games(self.entries(2, games_total=3))   # game 3 played, no winner recorded
        self.assertEqual((p.games_seen, p.games_done), (3, 2))
        self.assertEqual(comp.analyze_games([]).games_seen, 0)

    def test_gap_in_winners_stops_the_count(self):
        # game 2 has no winner but game 3 does: only game 1 counts as "done"
        a = [_sess("g1", self.at(20), 1), _sess("g2", self.at(40), 2), _sess("g3", self.at(60), 1)]
        p = comp.analyze_games([{"sessionHistory": a}])
        self.assertEqual(p.games_done, 1)

    def test_final_needs_the_last_game_won(self):
        close = self.T0 + timedelta(minutes=150)
        now = close + timedelta(hours=1)  # an hour AFTER the close, and still not over
        v = comp.decide_over(now=now, window_end=close, lobby="set", expected_games=10, progress=comp.analyze_games(self.entries(9, games_total=10)))
        self.assertFalse(v.over)  # game 10 has no winner yet
        v = comp.decide_over(now=now, window_end=close, lobby="set", expected_games=10, progress=comp.analyze_games(self.entries(10)))
        self.assertTrue(v.over)
        self.assertEqual(v.over_at, self.T0 + timedelta(minutes=200))  # when game 10 ended, not the close time
        # one game short of the count never counts as over, even long after the close...
        v = comp.decide_over(now=close + timedelta(minutes=90), window_end=close, lobby="set", expected_games=10, progress=comp.analyze_games(self.entries(9)))
        self.assertFalse(v.over)

    def test_safety_valve(self):
        close = self.T0 + timedelta(minutes=150)
        v = comp.decide_over(now=close + timedelta(hours=4), window_end=close, lobby="set", expected_games=10, progress=comp.analyze_games(self.entries(8)))
        self.assertTrue(v.over)  # nothing played for ages and 3h past the close

    def test_unknown_game_count(self):
        close = self.T0 + timedelta(minutes=100)
        p = comp.analyze_games(self.entries(4))  # last game ended at +80 min
        self.assertFalse(comp.decide_over(now=close - timedelta(minutes=5), window_end=close, lobby="set", expected_games=None, progress=p).over)
        # closed, but a game finished 10 minutes ago: still going
        busy = comp.analyze_games(self.entries(5))  # last game ended at +100
        self.assertFalse(comp.decide_over(now=close + timedelta(minutes=10), window_end=close, lobby="set", expected_games=0, progress=busy).over)
        self.assertTrue(comp.decide_over(now=close + timedelta(minutes=40), window_end=close, lobby="set", expected_games=0, progress=busy).over)

    def test_open_round_uses_the_close_plus_grace(self):
        close = self.T0
        p = comp.GameProgress()
        self.assertFalse(comp.decide_over(now=close + timedelta(minutes=20), window_end=close, lobby="open", expected_games=6, progress=p).over)
        v = comp.decide_over(now=close + timedelta(minutes=50), window_end=close, lobby="open", expected_games=6, progress=p)
        self.assertTrue(v.over)
        self.assertEqual(v.over_at, close)


class TestHiddenFamily(unittest.TestCase):
    def test_arenas_removed(self):
        for text in ("Arenas Cash Cup — Nov 10, 2026", "epicgames_S43_ArenaCashCup_EU", "Season42_ArenaCashCup", "Arenas Test Cup", "S42_ArenaTestCup_Event9_EU"):
            self.assertTrue(tp.is_hidden_family(text), text)
        for text in ("Trios Cash Cup", "Solo Series", "FNCS Division 1", "Arenas Performance Evaluation", None):
            self.assertFalse(tp.is_hidden_family(text), text)


if __name__ == "__main__":
    unittest.main()
