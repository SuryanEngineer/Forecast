"""Performance Evaluation cup dividend rules (pure functions). Run: python3 -m unittest discover -s tests -v"""
import os
import sys
import unittest
from decimal import Decimal as D

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.engine import performance_eval as pe


def session(place):
    return {"sessionId": f"s{place}", "trackedStats": {"PLACEMENT_STAT_INDEX": place}}


def entry(placements, players=3):
    return {"players": [{"accountId": str(i)} for i in range(players)], "sessionHistory": [session(p) for p in placements]}


class TestWins(unittest.TestCase):
    def test_counts_only_first_place_games(self):
        self.assertEqual(pe.count_game_wins(entry([1, 5, 1, 12])), 2)
        self.assertEqual(pe.count_game_wins(entry([2, 3, 9])), 0)
        self.assertEqual(pe.count_game_wins(None), 0)
        self.assertEqual(pe.count_game_wins({}), 0)

    def test_placement_key_variants_and_junk(self):
        self.assertEqual(pe.count_game_wins({"sessionHistory": [{"trackedStats": {"PLACEMENT": "1"}}, {"trackedStats": {}}, {}]}), 1)
        self.assertEqual(pe.count_game_wins({"sessionHistory": [{"trackedStats": {"PLACEMENT_STAT_INDEX": "x"}}]}), 0)

    def test_team_size(self):
        self.assertEqual(pe.team_size(entry([], players=2)), 2)
        self.assertEqual(pe.team_size({}), 3)  # default is a trio


class TestPools(unittest.TestCase):
    POOL, SHARE = D("300000"), D("0.25")

    def test_trio_win_is_25k_per_player(self):
        self.assertEqual(pe.per_player_win_value(self.POOL, self.SHARE, 3), D("25000.00"))
        self.assertEqual(pe.player_pool(entry([1]), self.POOL, self.SHARE), D("25000.00"))

    def test_two_wins_pay_twice_and_no_wins_pay_nothing(self):
        self.assertEqual(pe.player_pool(entry([1, 4, 1]), self.POOL, self.SHARE), D("50000.00"))
        self.assertEqual(pe.player_pool(entry([3, 7]), self.POOL, self.SHARE), D("0.00"))

    def test_other_team_sizes_split_the_same_quarter(self):
        self.assertEqual(pe.player_pool(entry([1], players=2), self.POOL, self.SHARE), D("37500.00"))
        self.assertEqual(pe.player_pool(entry([1], players=1), self.POOL, self.SHARE), D("75000.00"))
        self.assertEqual(pe.player_pool(entry([1], players=4), self.POOL, self.SHARE), D("18750.00"))

    def test_a_full_cup_of_four_trio_wins_costs_exactly_the_pool(self):
        total = sum((pe.player_pool(entry([1]), self.POOL, self.SHARE) * 3 for _ in range(4)), D("0"))
        self.assertEqual(total, self.POOL)


class TestLobbySize(unittest.TestCase):
    def test_set_lobbies_are_accepted(self):
        # 100 players (34 trios ~ 102 players), 80, 78 (26 trios), 40.
        for players in (100, 102, 80, 78, 40):
            self.assertTrue(pe.lobby_is_acceptable(players, 1), players)

    def test_paging_does_not_reject_a_set_lobby(self):
        # A 100-player lobby that Osirion splits over 2 or 3 pages is still fine (lower bound only).
        self.assertTrue(pe.lobby_is_acceptable(51, 2))
        self.assertTrue(pe.lobby_is_acceptable(40, 3))

    def test_open_fields_are_rejected(self):
        self.assertFalse(pe.lobby_is_acceptable(300, 1))
        self.assertFalse(pe.lobby_is_acceptable(99, 5))
        self.assertFalse(pe.lobby_is_acceptable(100, 30))


if __name__ == "__main__":
    unittest.main()
