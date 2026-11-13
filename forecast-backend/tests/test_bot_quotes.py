"""Bot quoting math (pure functions in engine/market_policy.py): quotes sit a hair either side of the bot's own value."""
import unittest

from app.engine import market_policy as mp


class RestingQuotes(unittest.TestCase):
    def test_quotes_sit_the_fee_plus_a_hair_either_side_of_value(self):
        # value $10, fee 0.25% + 0.2% slack: bid ~9.955, ask ~10.045 (a spread of about 0.9%)
        bid, ask = mp.resting_quote_prices(10.0, 10.0, 0.0045, 0.03)
        self.assertAlmostEqual(bid, 9.955, places=3)
        self.assertAlmostEqual(ask, 10.045, places=3)
        self.assertLess((ask - bid) / 10.0, 0.01)

    def test_a_bot_that_thinks_the_stock_is_cheap_bids_above_the_price_but_within_reach(self):
        bid, ask = mp.resting_quote_prices(12.0, 10.0, 0.0045, 0.03)   # values it 20% above the price
        self.assertAlmostEqual(bid, 10.3, places=3)                    # capped at price x (1 + reach)
        self.assertGreater(ask, bid)                                   # the ask follows its value: 12.05 (capped by ceil)

    def test_a_bot_that_thinks_it_is_dear_offers_below_the_price_but_within_reach(self):
        bid, ask = mp.resting_quote_prices(8.0, 10.0, 0.0045, 0.03)
        self.assertAlmostEqual(ask, 9.7, places=3)                     # floored at price x (1 - reach)
        self.assertLess(bid, ask)

    def test_floor_and_ceiling_bound_the_quotes(self):
        bid, ask = mp.resting_quote_prices(100.0, 10.0, 0.0045, 5.0)
        self.assertLessEqual(ask, 12.5)
        bid, ask = mp.resting_quote_prices(0.1, 10.0, 0.0045, 5.0)
        self.assertGreaterEqual(bid, 8.5)

    def test_two_bots_with_similar_values_leave_a_tight_book_and_far_apart_values_overlap(self):
        a_bid, a_ask = mp.resting_quote_prices(100.0, 100.0, 0.0045, 0.03)
        b_bid, b_ask = mp.resting_quote_prices(100.4, 100.0, 0.0050, 0.03)
        best_bid, best_ask = max(a_bid, b_bid), min(a_ask, b_ask)
        self.assertLess(best_ask - best_bid, 1.0)                      # under 1% of the price
        c_bid, _ = mp.resting_quote_prices(103.0, 100.0, 0.0045, 0.03)  # a much more bullish bot bids above A's ask: a trade
        self.assertGreater(c_bid, a_ask)


class MakerSpread(unittest.TestCase):
    def test_calm_stock_quotes_the_fee_plus_edge(self):
        self.assertAlmostEqual(mp.maker_half_spread(0.0025, 0.0015, 0.0), 0.004, places=6)

    def test_widening_after_a_sharp_move_is_capped_at_one_and_a_half_times(self):
        wide = mp.maker_half_spread(0.0025, 0.0015, 0.5)
        self.assertAlmostEqual(wide, 0.004 * 1.5, places=6)
        self.assertLess(wide, 0.01)                                    # under 1% each side even then (old: up to 6%)

    def test_direction_of_the_move_does_not_matter(self):
        self.assertEqual(mp.maker_half_spread(0.0025, 0.0015, -0.05), mp.maker_half_spread(0.0025, 0.0015, 0.05))


if __name__ == "__main__":
    unittest.main()
