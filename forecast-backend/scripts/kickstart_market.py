#!/usr/bin/env python3
"""
Runs many bot-trading ticks back to back (the same run_bot_tick the
background loop calls every BOT_TICK_INTERVAL_SECONDS on its own -- see
app/main.py and app/services/bot_trading_service.py) so a freshly
backfilled roster gets real price discovery quickly, instead of waiting
on the natural 20s-interval loop to slowly work through however many
players scripts/backfill_historical_market.py just IPO'd.

Each tick's bots buy/sell biased toward whichever players are most
mispriced relative to their own fair value (ipo_price scaled by a
recency-weighted, career-placement-curve expected-value estimate -- see
bot_trading_service.py's module comment on _compute_fair_value for the
full reasoning), so running a burst of these is really just fast-forwarding
the same organic price discovery the app already does on its own, not a
separate/different mechanism.

The live loop deliberately places only a few orders per tick (BOT_ACTIONS_PER_TICK, BOT_MM_PLAYERS_PER_TICK) to protect
the database's free-plan limits; this script raises both for the duration of the run so a fresh roster gets priced
quickly. Run it against a database you are happy to write a few thousand rows to.

Usage:
    cd forecast-backend
    python3 scripts/kickstart_market.py            # 100 ticks (default), 40 orders + 30 maker quotes per tick
    python3 scripts/kickstart_market.py --ticks 300 --orders 60 --maker-quotes 40
"""
from __future__ import annotations

import argparse
import random
import sys

sys.path.insert(0, ".")

from app.db.session import SessionLocal  # noqa: E402
from app.services import bot_trading_service  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ticks", type=int, default=100, help="Number of bot ticks to run (default: 100).")
    parser.add_argument("--orders", type=int, default=40, help="Orders the bot population may place per tick (default 40).")
    parser.add_argument("--maker-quotes", type=int, default=30, help="Market-maker player re-quotes per tick (default 30).")
    args = parser.parse_args()
    from app.core.config import settings  # noqa: E402

    settings.BOT_ACTIONS_PER_TICK = max(1, args.orders)
    settings.BOT_MM_PLAYERS_PER_TICK = max(1, args.maker_quotes)
    bot_trading_service.reset_caches()

    rng = random.Random()
    db = SessionLocal()
    total_actions = 0
    total_errors = 0
    try:
        for i in range(1, args.ticks + 1):
            result = bot_trading_service.run_bot_tick(db, rng)
            total_actions += result["actions"]
            total_errors += result["errors"]
            if i % 10 == 0 or i == args.ticks:
                print(
                    f"tick {i}/{args.ticks}: population={result['population']} active={result['active']} "
                    f"actions={result['actions']} errors={result['errors']} "
                    f"(running total: {total_actions} actions, {total_errors} errors)"
                )
        print(f"\nDone. {total_actions} bot orders placed/filled across {args.ticks} ticks.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
