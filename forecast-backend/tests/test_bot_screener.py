"""The bots' market screener: it flags players whose price is far from the model value, without setting any price."""
import os
import sys
import tempfile
import unittest
import uuid
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TMP = tempfile.mkdtemp(prefix="forecast_screener_")
os.environ.update({  # a throwaway database, set BEFORE the app is imported (never the real one)
    "FORECAST_ENV_FILE": os.path.join(_TMP, "none.env"), "DATABASE_URL": f"sqlite:///{os.path.join(_TMP, 't.db')}",
    "REDIS_ENABLED": "false", "BOT_TRADING_ENABLED": "false", "OSIRION_SYNC_ENABLED": "false",
})

from app.services import bot_trading_service as bts  # noqa: E402


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
