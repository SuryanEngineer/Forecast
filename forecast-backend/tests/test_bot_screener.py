"""The bots' market screener: it flags players whose price is far from the model value, without setting any price."""
import unittest
import uuid
from decimal import Decimal

from app.services import bot_trading_service as bts


class ScreenerTests(unittest.TestCase):
    def test_flags_price_far_from_model(self):
        a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        signals = {a: {}, b: {}, c: {}}
        price = {a: Decimal("100"), b: Decimal("100"), c: Decimal("100")}
        model = {a: Decimal("100"), b: Decimal("70"), c: Decimal("101")}   # b was marked down hard (e.g. missed the cut)
        movers = bts._find_movers({}, signals, {}, price, model)
        self.assertEqual(movers, [b])

    def test_louder_gap_comes_first(self):
        a, b = uuid.uuid4(), uuid.uuid4()
        price = {a: Decimal("100"), b: Decimal("100")}
        model = {a: Decimal("80"), b: Decimal("60")}
        movers = bts._find_movers({}, {a: {}, b: {}}, {}, price, model)
        self.assertEqual(movers, [b, a])

    def test_old_signature_still_works(self):
        a = uuid.uuid4()
        self.assertEqual(bts._find_movers({a: Decimal("0.10")}, {a: {}}, {}), [a])


if __name__ == "__main__":
    unittest.main()
