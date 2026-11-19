"""With the market anchor on, the size of the dividend pools must not move any price (pure logic; no database)."""
import unittest

from app.engine import market_policy as mp

INC = [0.5, 2.0, 5.0, 12.0, 30.0]        # projected yearly dividends per share
SH = [1000, 800, 1200, 500, 900]
ANCHOR = 400_000.0


def fair(inc, y):
    return [min(5000.0, max(1.0, i / y)) for i in inc]


class AnchorTests(unittest.TestCase):
    def test_total_fair_value_equals_anchor(self):
        y = mp.solve_target_yield(INC, SH, ANCHOR)
        total = sum(f * s for f, s in zip(fair(INC, y), SH))
        self.assertAlmostEqual(total, ANCHOR, delta=1.0)

    def test_scaling_every_pool_leaves_prices_unchanged(self):
        y1 = mp.solve_target_yield(INC, SH, ANCHOR)
        for k in (0.5, 2.0, 7.0):
            scaled = [i * k for i in INC]
            yk = mp.solve_target_yield(scaled, SH, ANCHOR)
            self.assertAlmostEqual(yk, y1 * k, delta=1e-6)                  # the yield absorbs the pool size...
            for a, b in zip(fair(INC, y1), fair(scaled, yk)):
                self.assertAlmostEqual(a, b, delta=1e-4)                    # ...so every price stays put

    def test_relative_dividends_still_move_prices(self):
        y = mp.solve_target_yield(INC, SH, ANCHOR)
        before = fair(INC, y)
        better = list(INC)
        better[0] *= 10                                                      # one stock starts earning 10x more
        y2 = mp.solve_target_yield(better, SH, ANCHOR)
        after = fair(better, y2)
        self.assertGreater(after[0], before[0])
        self.assertLess(after[4], before[4])                                 # the rest give up share of a fixed total


if __name__ == "__main__":
    unittest.main()
