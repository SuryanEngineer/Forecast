"""
Real, runnable unit tests for the pure engines (no third-party deps).

Run with:  python3 -m unittest discover -s tests -v
(from the forecast-backend/ directory)
"""
import sys
import os
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.engine.matching_engine import OrderBook
from app.engine.types import Side
from app.engine.quick_trade_pricing import execute_quick_order, estimate_quick_order_cost, default_synthetic_depth
from app.engine.dividend_calculator import compute_player_pool, compute_dividend_distribution
from app.engine.treasury_calculator import accrue_interest, redemption_value
from app.engine.auction_calculator import BidInput, settle_player_auction


class TestMatchingEngine(unittest.TestCase):
    def test_limit_orders_rest_when_no_cross(self):
        book = OrderBook("player-1")
        book.add_limit_order("b1", Side.BUY, Decimal("10.00"), Decimal("5"))
        book.add_limit_order("s1", Side.SELL, Decimal("11.00"), Decimal("5"))
        self.assertEqual(book.best_bid.price, Decimal("10.00"))
        self.assertEqual(book.best_ask.price, Decimal("11.00"))
        self.assertIsNone(book.last_trade_price)

    def test_crossing_limit_order_fills_at_maker_price(self):
        book = OrderBook("player-1")
        book.add_limit_order("s1", Side.SELL, Decimal("10.00"), Decimal("5"))
        result = book.add_limit_order("b1", Side.BUY, Decimal("10.50"), Decimal("5"))
        self.assertEqual(len(result.fills), 1)
        self.assertEqual(result.fills[0].price, Decimal("10.00"))  # maker's price, not taker's
        self.assertEqual(result.fills[0].quantity, Decimal("5"))
        self.assertEqual(result.remaining_quantity, Decimal("0"))
        self.assertEqual(book.last_trade_price, Decimal("10.00"))

    def test_price_time_priority(self):
        book = OrderBook("player-1")
        # two asks at the same price, first one in should fill first
        book.add_limit_order("s1", Side.SELL, Decimal("10.00"), Decimal("3"))
        book.add_limit_order("s2", Side.SELL, Decimal("10.00"), Decimal("3"))
        result = book.add_limit_order("b1", Side.BUY, Decimal("10.00"), Decimal("4"))
        self.assertEqual(result.fills[0].maker_order_id, "s1")
        self.assertEqual(result.fills[0].quantity, Decimal("3"))
        self.assertEqual(result.fills[1].maker_order_id, "s2")
        self.assertEqual(result.fills[1].quantity, Decimal("1"))

    def test_partial_fill_rests_remainder(self):
        book = OrderBook("player-1")
        book.add_limit_order("s1", Side.SELL, Decimal("10.00"), Decimal("2"))
        result = book.add_limit_order("b1", Side.BUY, Decimal("10.00"), Decimal("5"))
        self.assertEqual(result.filled_quantity, Decimal("2"))
        self.assertEqual(result.remaining_quantity, Decimal("3"))
        self.assertEqual(book.best_bid.remaining, Decimal("3"))

    def test_cancel_removes_order_from_book(self):
        book = OrderBook("player-1")
        book.add_limit_order("b1", Side.BUY, Decimal("10.00"), Decimal("5"))
        self.assertTrue(book.cancel("b1"))
        self.assertIsNone(book.best_bid)
        self.assertFalse(book.cancel("b1"))  # already cancelled

    def test_bot_liquidity_indistinguishable_from_user_liquidity(self):
        book = OrderBook("player-1")
        book.add_limit_order("bot-1", Side.SELL, Decimal("10.00"), Decimal("5"), is_bot=True)
        result = book.add_limit_order("b1", Side.BUY, Decimal("10.00"), Decimal("5"))
        self.assertTrue(result.fills[0].maker_is_bot)


class TestQuickTradePricing(unittest.TestCase):
    def test_quick_buy_fully_filled_by_book(self):
        book = OrderBook("player-1")
        book.add_limit_order("s1", Side.SELL, Decimal("10.00"), Decimal("10"), is_bot=True)
        result = execute_quick_order(
            book, "q1", Side.BUY, Decimal("5"), shares_outstanding=Decimal("1000")
        )
        self.assertEqual(result.book_filled_quantity, Decimal("5"))
        self.assertEqual(result.synthetic_filled_quantity, Decimal("0"))
        self.assertEqual(result.vwap, Decimal("10.00"))

    def test_quick_buy_falls_back_to_synthetic_liquidity_when_book_thin(self):
        book = OrderBook("player-1")
        book.add_limit_order("s1", Side.SELL, Decimal("10.00"), Decimal("2"), is_bot=True)
        result = execute_quick_order(
            book, "q1", Side.BUY, Decimal("10"), shares_outstanding=Decimal("1000"),
            fallback_reference_price=Decimal("10.00"),
        )
        self.assertEqual(result.book_filled_quantity, Decimal("2"))
        self.assertEqual(result.synthetic_filled_quantity, Decimal("8"))
        self.assertEqual(result.unfilled_quantity, Decimal("0"))
        # synthetic price should be higher than reference (buy pressure)
        synthetic_fill = result.fills[-1]
        self.assertGreater(synthetic_fill.price, Decimal("10.00"))

    def test_quick_sell_synthetic_price_never_below_min(self):
        book = OrderBook("player-1")
        result = execute_quick_order(
            book, "q1", Side.SELL, Decimal("100000"), shares_outstanding=Decimal("1000"),
            fallback_reference_price=Decimal("1.00"),
        )
        self.assertGreaterEqual(result.fills[-1].price, Decimal("0.01"))

    def test_quick_order_with_no_liquidity_and_no_fallback_is_unfilled(self):
        book = OrderBook("player-1")
        result = execute_quick_order(book, "q1", Side.BUY, Decimal("5"), shares_outstanding=Decimal("1000"))
        self.assertEqual(result.unfilled_quantity, Decimal("5"))
        self.assertEqual(result.total_filled_quantity, Decimal("0"))

    def test_estimate_matches_actual_execution_exactly(self):
        """Under a held lock (guaranteed by book_registry.py in practice),
        the estimate and the real execution must agree exactly -- this is
        the safety property order_service.py relies on to pre-check funds
        before mutating the book."""
        book = OrderBook("player-1")
        book.add_limit_order("s1", Side.SELL, Decimal("10.00"), Decimal("2"), is_bot=True)
        book.add_limit_order("s2", Side.SELL, Decimal("10.50"), Decimal("5"), is_bot=True)

        estimated = estimate_quick_order_cost(
            book, Side.BUY, Decimal("10"), shares_outstanding=Decimal("1000"),
            fallback_reference_price=Decimal("10.00"),
        )
        result = execute_quick_order(
            book, "q1", Side.BUY, Decimal("10"), shares_outstanding=Decimal("1000"),
            fallback_reference_price=Decimal("10.00"),
        )
        actual = sum(f.price * f.quantity for f in result.fills)
        self.assertEqual(estimated, actual)

    def test_estimate_none_when_no_book_and_no_fallback(self):
        book = OrderBook("player-1")
        estimated = estimate_quick_order_cost(book, Side.BUY, Decimal("5"), shares_outstanding=Decimal("1000"))
        self.assertIsNone(estimated)

    def test_default_synthetic_depth_has_floor(self):
        self.assertEqual(default_synthetic_depth(Decimal("100")), Decimal("100"))  # 1% would be 1, floor is 100
        self.assertEqual(default_synthetic_depth(Decimal("100000")), Decimal("1000"))  # 1% of 100k

    def test_synthetic_buy_leaves_order_unfilled_when_house_inventory_exhausted(self):
        """Regression test: a BUY quick order used to be able to synthesize
        a fill for more shares than the House actually owned of a player,
        which the database's positions.quantity conservation constraint
        would then reject with a raw, unhandled IntegrityError deep in
        settlement (see order_service.place_quick_order's
        max_synthetic_quantity wiring). The engine layer must refuse to
        synthesize past that cap instead.

        Note: the REAL book-matched portion (backed by an actual resting
        seller, not House inventory) still fills normally -- only the
        synthetic leftover is refused. In production this exact partial
        state is never actually reached, because
        order_service.place_quick_order calls estimate_quick_order_cost
        FIRST and rejects the whole order (see
        test_estimate_none_when_house_inventory_cap_exceeded below)
        before execute_quick_order -- and therefore this book match --
        ever runs. This test exercises execute_quick_order's own
        standalone defensive behavior in isolation."""
        book = OrderBook("player-1")
        book.add_limit_order("s1", Side.SELL, Decimal("10.00"), Decimal("2"), is_bot=True)
        # House only has 3 shares left of this player -- book covers 2 of
        # the requested 10, leaving 8 to synthesize, which exceeds the cap.
        result = execute_quick_order(
            book, "q1", Side.BUY, Decimal("10"), shares_outstanding=Decimal("1000"),
            fallback_reference_price=Decimal("10.00"), max_synthetic_quantity=Decimal("3"),
        )
        self.assertEqual(result.book_filled_quantity, Decimal("2"))
        self.assertEqual(result.synthetic_filled_quantity, Decimal("0"))
        self.assertEqual(result.unfilled_quantity, Decimal("8"))

    def test_synthetic_buy_fills_normally_within_house_inventory_cap(self):
        book = OrderBook("player-1")
        result = execute_quick_order(
            book, "q1", Side.BUY, Decimal("10"), shares_outstanding=Decimal("1000"),
            fallback_reference_price=Decimal("10.00"), max_synthetic_quantity=Decimal("50"),
        )
        self.assertEqual(result.synthetic_filled_quantity, Decimal("10"))
        self.assertEqual(result.unfilled_quantity, Decimal("0"))

    def test_estimate_none_when_house_inventory_cap_exceeded(self):
        book = OrderBook("player-1")
        estimated = estimate_quick_order_cost(
            book, Side.BUY, Decimal("10"), shares_outstanding=Decimal("1000"),
            fallback_reference_price=Decimal("10.00"), max_synthetic_quantity=Decimal("3"),
        )
        self.assertIsNone(estimated)

    def test_estimate_refusal_prevents_execute_from_ever_running_in_practice(self):
        """order_service.place_quick_order's actual sequence is: call
        estimate_quick_order_cost first, and only call execute_quick_order
        at all if that succeeds. So the real safety property isn't that
        the two functions produce numerically identical partial results
        if you call both against the same cap-exceeding scenario (they
        don't have to -- see the note on
        test_synthetic_buy_leaves_order_unfilled_when_house_inventory_exhausted
        above) -- it's that estimate reliably refuses (returns None)
        every time the cap would be exceeded, which is what actually
        stops execute_quick_order (and the real book mutation inside it)
        from ever being reached for these orders in production."""
        book = OrderBook("player-1")
        book.add_limit_order("s1", Side.SELL, Decimal("10.00"), Decimal("2"), is_bot=True)
        estimated = estimate_quick_order_cost(
            book, Side.BUY, Decimal("10"), shares_outstanding=Decimal("1000"),
            fallback_reference_price=Decimal("10.00"), max_synthetic_quantity=Decimal("3"),
        )
        self.assertIsNone(estimated)

    def test_sell_side_has_no_house_inventory_cap(self):
        """SELL quick orders are never capped by max_synthetic_quantity --
        the House buying shares back is only constrained by cash, not
        share supply, so passing a cap here should have no effect."""
        book = OrderBook("player-1")
        result = execute_quick_order(
            book, "q1", Side.SELL, Decimal("10"), shares_outstanding=Decimal("1000"),
            fallback_reference_price=Decimal("10.00"), max_synthetic_quantity=None,
        )
        self.assertEqual(result.synthetic_filled_quantity, Decimal("10"))
        self.assertEqual(result.unfilled_quantity, Decimal("0"))


class TestDividendCalculator(unittest.TestCase):
    def test_uses_exact_prize_won_when_given(self):
        pool = compute_player_pool(
            placement=1, prize_won=Decimal("5000.00"), tournament_prize_pool=Decimal("100000"), max_placement=100
        )
        self.assertEqual(pool, Decimal("5000.00"))

    def test_falls_back_to_curve_when_no_exact_prize(self):
        pool = compute_player_pool(
            placement=1, prize_won=None, tournament_prize_pool=Decimal("100000"), max_placement=100
        )
        self.assertEqual(pool, Decimal("20000.00"))  # 20% of 100k

    def test_placement_outside_field_gets_zero(self):
        # placement 999 doesn't exist in a 100-placement field -- still
        # zero, same as before this fix, just now bounded by max_placement
        # instead of "anything not in the hardcoded curve dict."
        pool = compute_player_pool(
            placement=999, prize_won=None, tournament_prize_pool=Decimal("100000"), max_placement=100
        )
        self.assertEqual(pool, Decimal("0"))

    def test_placement_past_explicit_curve_gets_nonzero_tail_payout(self):
        # Before this fix, placement 50 (past the explicit curve's top 12)
        # got flat $0 no matter how big the field was. Now it should get a
        # small but real sliver of the remaining budget.
        pool = compute_player_pool(
            placement=50, prize_won=None, tournament_prize_pool=Decimal("100000"), max_placement=100
        )
        self.assertGreater(pool, Decimal("0"))
        self.assertLess(pool, Decimal("2500.00"))  # well below even the smallest explicit-curve payout (2.5% = $2500)

    def test_full_field_curve_sums_to_approximately_whole_pool(self):
        from app.engine.dividend_calculator import DEFAULT_PLACEMENT_CURVE, placement_payout_fraction

        total = sum(
            (placement_payout_fraction(p, 100, DEFAULT_PLACEMENT_CURVE) for p in range(1, 101)),
            Decimal("0"),
        )
        self.assertAlmostEqual(float(total), 1.0, places=6)

    def test_distribution_sums_exactly_to_pool_minus_fee_no_leftover_pennies(self):
        holders = [("user-a", Decimal("3")), ("user-b", Decimal("3")), ("user-c", Decimal("4"))]
        per_share, payouts, fee = compute_dividend_distribution(
            pool_amount=Decimal("1000.00"),
            shares_outstanding=Decimal("10"),
            holders=holders,
            platform_fee_pct=Decimal("0.05"),
        )
        self.assertEqual(fee, Decimal("50.00"))
        total_paid = sum(amt for _, amt in payouts)
        self.assertEqual(total_paid, Decimal("950.00"))  # every cent accounted for

    def test_distribution_handles_rounding_remainder_fairly(self):
        # 100 / 3 shares does not divide evenly in cents
        holders = [("user-a", Decimal("1")), ("user-b", Decimal("1")), ("user-c", Decimal("1"))]
        per_share, payouts, fee = compute_dividend_distribution(
            pool_amount=Decimal("100.00"),
            shares_outstanding=Decimal("3"),
            holders=holders,
        )
        total_paid = sum(amt for _, amt in payouts)
        self.assertEqual(total_paid, Decimal("100.00"))
        # each holder gets either 33.33 or 33.34
        for _, amt in payouts:
            self.assertIn(amt, (Decimal("33.33"), Decimal("33.34")))

    def test_zero_pool_pays_nothing(self):
        per_share, payouts, fee = compute_dividend_distribution(
            pool_amount=Decimal("0"), shares_outstanding=Decimal("10"),
            holders=[("user-a", Decimal("10"))],
        )
        self.assertEqual(payouts, [("user-a", Decimal("0.00"))])


class TestTreasuryCalculator(unittest.TestCase):
    def test_accrue_one_day(self):
        interest = accrue_interest(Decimal("1000.00"), Decimal("0.04"), Decimal("1"))
        # 1000 * 0.04 / 365 = 0.1095890... -> floored to cent
        self.assertEqual(interest, Decimal("0.10"))

    def test_accrue_zero_principal(self):
        self.assertEqual(accrue_interest(Decimal("0"), Decimal("0.04")), Decimal("0.00"))

    def test_redemption_value(self):
        self.assertEqual(redemption_value(Decimal("1000.00"), Decimal("12.34")), Decimal("1012.34"))


class TestAuctionCalculator(unittest.TestCase):
    def test_even_split_exact(self):
        # Two equal $100 bids, 100 shares -> total demand $200, clearing
        # price $2.00/share, 50 shares each, each bidder's full $100 bid
        # exactly covers their 50 shares (no rounding shortfall at all).
        bids = [BidInput("b1", "u1", Decimal("100")), BidInput("b2", "u2", Decimal("100"))]
        settlement = settle_player_auction(bids, shares_available=100)
        self.assertEqual(settlement.clearing_price, Decimal("2.0000"))
        shares = {a.bid_id: a.shares_won for a in settlement.allocations}
        self.assertEqual(shares, {"b1": 50, "b2": 50})
        for a in settlement.allocations:
            self.assertEqual(a.amount_charged, Decimal("100.0000"))
            self.assertEqual(a.amount_released, Decimal("0"))

    def test_share_conservation_with_uneven_bids_that_dont_divide_evenly(self):
        # 3 bidders, 10 shares, bids of 1/3 each -- classic non-terminating
        # division case that a naive independent-rounding approach gets
        # wrong (this is exactly the bug found and fixed in forecast_sim).
        bids = [BidInput(f"b{i}", f"u{i}", Decimal("100")) for i in range(3)]
        settlement = settle_player_auction(bids, shares_available=10)
        total_shares = sum(a.shares_won for a in settlement.allocations)
        self.assertEqual(total_shares, 10)  # must conserve exactly, not 9 or 11

    def test_many_bidders_odd_share_count_always_conserves(self):
        # Sweep a range of bidder counts and share counts to build
        # confidence the conservation property holds broadly, not just
        # for hand-picked numbers.
        import random
        rng = random.Random(42)
        for shares_available in (1, 3, 7, 13, 100, 9999):
            for num_bidders in (1, 2, 3, 5, 17):
                bids = [
                    BidInput(f"b{i}", f"u{i}", Decimal(rng.randint(1, 100_000)) / Decimal("100"))
                    for i in range(num_bidders)
                ]
                settlement = settle_player_auction(bids, shares_available=shares_available)
                total_shares = sum(a.shares_won for a in settlement.allocations)
                self.assertEqual(
                    total_shares, shares_available,
                    f"shares={shares_available} bidders={num_bidders}: got {total_shares}",
                )

    def test_no_bidder_ever_charged_more_than_their_bid(self):
        # A deliberately adversarial case: one bidder with a tiny bid
        # relative to a huge share count, where naive proportional math
        # would round them into owing more than they bid.
        bids = [BidInput("whale", "u1", Decimal("999999")), BidInput("minnow", "u2", Decimal("1"))]
        settlement = settle_player_auction(bids, shares_available=7)
        for a in settlement.allocations:
            bid_amount = {"whale": Decimal("999999"), "minnow": Decimal("1")}[a.bid_id]
            self.assertLessEqual(a.amount_charged, bid_amount)
            self.assertEqual(a.amount_charged + a.amount_released, bid_amount)

    def test_single_bidder_wins_everything(self):
        bids = [BidInput("only", "u1", Decimal("12345.67"))]
        settlement = settle_player_auction(bids, shares_available=50)
        self.assertEqual(settlement.allocations[0].shares_won, 50)
        self.assertEqual(settlement.clearing_price, (Decimal("12345.67") / 50).quantize(Decimal("0.0001")))

    def test_zero_shares_available_raises(self):
        with self.assertRaises(ValueError):
            settle_player_auction([BidInput("b1", "u1", Decimal("10"))], shares_available=0)

    def test_empty_bids_raises(self):
        with self.assertRaises(ValueError):
            settle_player_auction([], shares_available=10)

    def test_tie_broken_deterministically_by_user_id(self):
        # Two identical bids competing for one leftover share -- result
        # must be stable/reproducible, not order-dependent.
        bids = [BidInput("b_zzz", "zzz", Decimal("50")), BidInput("b_aaa", "aaa", Decimal("50"))]
        settlement1 = settle_player_auction(bids, shares_available=1)
        settlement2 = settle_player_auction(list(reversed(bids)), shares_available=1)
        winner1 = next(a.bid_id for a in settlement1.allocations if a.shares_won > 0)
        winner2 = next(a.bid_id for a in settlement2.allocations if a.shares_won > 0)
        self.assertEqual(winner1, winner2)
        self.assertEqual(winner1, "b_aaa")  # "aaa" sorts before "zzz" as the tie-break


if __name__ == "__main__":
    unittest.main()
