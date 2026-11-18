"""Per-game points and leaderboard position (pure logic; no database)."""
import unittest

from app.engine import game_standings as gs

RULES = [
    {"stat": "PLACEMENT_STAT_INDEX", "tiers": [[1, 5.0, False], [5, 3.0, False], [15, 1.0, False]]},
    {"stat": "TEAM_ELIMS_STAT_INDEX", "tiers": [[1, 1.0, True]]},
]


def teams_for(mode):
    """Four teams over three games, totals computed with the given reading, so choose_mode has something to recover."""
    games = {
        "a": {1: (1, 4), 2: (7, 2), 3: (3, 1)},
        "b": {1: (3, 2), 2: (1, 5), 3: (20, 0)},
        "c": {1: (9, 1), 2: (2, 3), 3: (1, 6)},
        "d": {1: (30, 0), 2: (12, 1), 3: (8, 2)},
    }
    out = []
    for k, g in games.items():
        total = sum(gs.game_points(RULES, p, e, mode) for p, e in g.values())
        out.append({"key": k, "total": total, "games": g})
    return out


class PointsTests(unittest.TestCase):
    def test_rules_from_score_location(self):
        loc = {"scoringRules": [
            {"trackedStat": "PLACEMENT_STAT_INDEX", "rewardTiers": [{"keyValue": 1, "pointsEarned": 5}]},
            {"trackedStat": "TEAM_ELIMS_STAT_INDEX", "rewardTiers": [{"keyValue": 1, "pointsEarned": 1, "multiplicative": True}]},
            {"trackedStat": "EMPTY", "rewardTiers": []},
        ]}
        rules = gs.rules_from_score_location(loc)
        self.assertEqual(len(rules), 2)
        self.assertEqual(rules[1]["tiers"], [[1.0, 1.0, True]])
        self.assertEqual(gs.rules_from_score_location(None), [])

    def test_best_reading(self):
        # 3rd place falls in the "top 5" tier (3 pts); 4 elims at 1 pt each
        self.assertEqual(gs.game_points(RULES, 3, 4, "best"), 3 + 4)
        self.assertEqual(gs.game_points(RULES, 1, 0, "best"), 5)
        self.assertEqual(gs.game_points(RULES, 30, 2, "best"), 2)   # outside every tier: elims only

    def test_cumulative_reading_adds_every_tier_reached(self):
        self.assertEqual(gs.game_points(RULES, 1, 0, "cumulative"), 5 + 3 + 1)

    def test_choose_mode_recovers_the_reading_that_matches_real_totals(self):
        for mode in ("best", "cumulative"):
            self.assertEqual(gs.choose_mode(RULES, teams_for(mode)), mode)

    def test_choose_mode_refuses_to_guess(self):
        wrong = teams_for("best")
        for t in wrong:
            t["total"] += 7   # totals that no reading reproduces
        self.assertIsNone(gs.choose_mode(RULES, wrong))
        self.assertIsNone(gs.choose_mode([], teams_for("best")))
        self.assertIsNone(gs.choose_mode(RULES, teams_for("best")[:2]))  # too few teams to judge


class ProgressTests(unittest.TestCase):
    def test_running_totals_and_positions_follow_game_numbers(self):
        per_game = {"a": {1: 10, 2: 0, 3: 5}, "b": {1: 4, 2: 12, 3: 0}, "c": {1: 0, 2: 3, 3: 20}}
        finals = {"a": 2, "b": 3, "c": 1}
        out = gs.build_progress(per_game, finals, {1: True, 2: True, 3: True}, 3)
        self.assertEqual([out[k][1][2] for k in "abc"], [1, 2, 3])        # after game 1: a 10, b 4, c 0
        self.assertEqual([out[k][2][2] for k in "abc"], [2, 1, 3])        # after game 2: a 10, b 16, c 3 -> b leads
        self.assertEqual(out["b"][2][1], 16.0)
        self.assertEqual([out[k][3][2] for k in "abc"], [3, 2, 1])        # after game 3: a 15, b 16, c 23

    def test_positions_after_game_two_rank_by_total(self):
        per_game = {"a": {1: 10, 2: 0}, "b": {1: 4, 2: 12}}
        out = gs.build_progress(per_game, {"a": 2, "b": 1}, {1: True, 2: True}, 2)
        self.assertEqual(out["a"][1][2], 1)
        self.assertEqual(out["b"][2][2], 1)      # b overtook a (16 vs 10)
        self.assertEqual(out["a"][2][2], 2)

    def test_incomplete_game_gets_no_entry_but_still_counts_in_later_totals(self):
        per_game = {"a": {1: 5, 2: 3}, "b": {1: 1, 2: 9}}
        out = gs.build_progress(per_game, {"a": 1, "b": 2}, {1: True, 2: False}, 2)
        self.assertIn(1, out["a"])
        self.assertNotIn(2, out["a"])

    def test_ties_break_by_final_placement(self):
        per_game = {"a": {1: 5}, "b": {1: 5}}
        out = gs.build_progress(per_game, {"a": 2, "b": 1}, {1: True}, 1)
        self.assertEqual(out["b"][1][2], 1)
        self.assertEqual(out["a"][1][2], 2)


if __name__ == "__main__":
    unittest.main()
