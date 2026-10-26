#!/usr/bin/env python3
"""
Give the existing bots varied bankrolls (a few big wallets, many small ones) so the leaderboard looks like a real
player base instead of everyone starting identical. Only ever DEPOSITS (never removes cash), only for bots (users with a
BotProfile), and each bot is topped up at most once per run to a log-normal multiple (>= 1.0x) of the starting balance.
Dry run unless --confirm.

    python3 scripts/diversify_bot_bankrolls.py
    python3 scripts/diversify_bot_bankrolls.py --confirm
"""
from __future__ import annotations

import argparse
import math
import random
import sys
from decimal import Decimal

sys.path.insert(0, ".")

from app.db.session import SessionLocal  # noqa: E402
from app.models.bot import BotProfile  # noqa: E402
from app.services import economic_params_service, wallet_service  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--confirm", action="store_true")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        start = economic_params_service.get_param(db, "wallet.starting_balance")
        rng = random.Random()
        bot_ids = [uid for (uid,) in db.query(BotProfile.user_id).all()]
        total = Decimal("0")
        for uid in bot_ids:
            mult = min(6.0, max(1.0, math.exp(rng.gauss(0.25, 0.6))))
            extra = (start * Decimal(str(round(mult - 1.0, 3)))).quantize(Decimal("1"))
            if extra <= 0:
                continue
            total += extra
            if args.confirm:
                wallet_service.get_or_create_wallet(db, uid)
                wallet_service.deposit(db, uid, extra, memo="Bot bankroll adjustment")
        print(f"{len(bot_ids)} bot(s); {'deposited' if args.confirm else 'would deposit'} ${total:,} in total.")
        if args.confirm:
            db.commit()
        else:
            print("Dry run only -- re-run with --confirm to apply.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
