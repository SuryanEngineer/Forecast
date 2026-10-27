#!/usr/bin/env python3
"""List every bot: name, strategy, cash. Read-only.   python3 scripts/list_bots.py"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from app.db.session import SessionLocal  # noqa: E402
from app.models.bot import BotProfile  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.wallet import Wallet  # noqa: E402


def main() -> None:
    db = SessionLocal()
    try:
        rows = (
            db.query(User.display_name, BotProfile.strategy, Wallet.cash_balance)
            .join(BotProfile, BotProfile.user_id == User.id)
            .outerjoin(Wallet, Wallet.user_id == User.id)
            .order_by(User.display_name)
            .all()
        )
        for name, strat, cash in rows:
            print(f"{name:<24} {strat:<20} ${float(cash or 0):>14,.0f}")
        print(f"\n{len(rows)} bots")
    finally:
        db.close()


if __name__ == "__main__":
    main()
