#!/usr/bin/env python3
"""
Reset every REAL user's account to a clean $10,000 start (bots and the House are not touched unless asked).

For each real user (everyone except bots and the House account):
  * open / partially-filled orders are CANCELLED (history kept) and held cash/shares released
  * every share they own is returned to the House (so each player's shares still sum to the fixed float)
  * active treasury holdings are marked redeemed WITHOUT paying out (the cash is being reset anyway)
  * cash is set to the amount (default 10000) with a ledger entry ("Account reset"), held cash = 0
  Their trade history, dividend history and ledger rows are kept; only balances/holdings change.

STOP THE BACKEND FIRST and restart it afterwards: the live order books are rebuilt from the database at startup, so a
running server would still hold the cancelled orders in memory.

Dry run by default (prints exactly what would change).

    python3 scripts/reset_user_accounts.py
    python3 scripts/reset_user_accounts.py --confirm
    python3 scripts/reset_user_accounts.py --confirm --amount 10000
    python3 scripts/reset_user_accounts.py --keep-holdings --confirm      # only reset cash; leave shares and orders alone
    python3 scripts/reset_user_accounts.py --email someone@example.com    # just one account
    python3 scripts/reset_user_accounts.py --include-bots --confirm       # also bots (cash + holdings back to the House)
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from decimal import Decimal

sys.path.insert(0, ".")

from sqlalchemy import func  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.bot import BotProfile  # noqa: E402
from app.models.order import Order, OrderStatus  # noqa: E402
from app.models.player import Position  # noqa: E402
from app.models.treasury import TreasuryHolding, TreasuryHoldingStatus  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.wallet import LedgerEntryType, Wallet  # noqa: E402
from app.services import wallet_service  # noqa: E402
from app.services.house_account import HOUSE_ACCOUNT_EMAIL, get_or_create_house_user  # noqa: E402
from app.services.position_service import get_or_create_position  # noqa: E402

_OPEN = (OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--amount", type=Decimal, default=Decimal("10000"))
    ap.add_argument("--keep-holdings", action="store_true", help="Only reset cash.")
    ap.add_argument("--include-bots", action="store_true")
    ap.add_argument("--email", default="", help="Only this user.")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        house = get_or_create_house_user(db)
        bot_ids = {r[0] for r in db.query(BotProfile.user_id).all()}
        users = db.query(User).filter(User.id != house.id).all()
        if args.email:
            users = [u for u in users if u.email.lower() == args.email.lower()]
        else:
            users = [u for u in users if args.include_bots or u.id not in bot_ids]
        print(f"{len(users)} account(s) to reset to ${args.amount:,.2f}"
              f"{' (cash only)' if args.keep_holdings else ' (cash + holdings + open orders)'}.\n")

        total_cash_before = Decimal("0")
        n_orders = n_positions = n_treasury = 0
        for u in users:
            w = wallet_service.get_or_create_wallet(db, u.id)
            before = w.cash_balance
            total_cash_before += before
            orders = db.query(Order).filter(Order.user_id == u.id, Order.status.in_(_OPEN)).all() if not args.keep_holdings else []
            positions = db.query(Position).filter(Position.user_id == u.id, Position.quantity > 0).all() if not args.keep_holdings else []
            treas = db.query(TreasuryHolding).filter(TreasuryHolding.user_id == u.id, TreasuryHolding.status == TreasuryHoldingStatus.ACTIVE).all() if not args.keep_holdings else []
            tag = " [bot]" if u.id in bot_ids else ""
            print(f"  {u.email:<40}{tag:<6} cash ${before:>14,.2f} -> ${args.amount:,.2f}   "
                  f"open orders={len(orders)}  holdings={len(positions)} ({sum(p.quantity for p in positions)} shares)  treasury={len(treas)}")
            n_orders += len(orders); n_positions += len(positions); n_treasury += len(treas)
            if not args.confirm:
                continue

            for o in orders:
                o.status = OrderStatus.CANCELLED
            for p in positions:
                hp = get_or_create_position(db, house.id, p.player_id)
                hp.quantity += p.quantity
                p.quantity = 0
                p.held_quantity = 0
                p.average_cost = Decimal("0")
            for t in treas:
                t.status = TreasuryHoldingStatus.REDEEMED
                t.redeemed_at = datetime.now(timezone.utc)
            if not args.keep_holdings:
                db.query(Position).filter(Position.user_id == u.id).update({"held_quantity": 0}, synchronize_session=False)

            delta = args.amount - before
            w.cash_balance = args.amount
            w.held_balance = Decimal("0")
            db.flush()
            if delta != 0:
                wallet_service._write_ledger_entry(  # noqa: SLF001 -- append-only audit row for the reset
                    db, w, LedgerEntryType.DEPOSIT if delta > 0 else LedgerEntryType.WITHDRAWAL, delta,
                    memo=f"Account reset to ${args.amount:,.2f}")
            db.commit()

        print(f"\nTotal cash across these accounts before: ${total_cash_before:,.2f}   after: ${args.amount * len(users):,.2f}")
        print(f"Open orders cancelled: {n_orders}   holdings returned to the House: {n_positions}   treasury holdings closed: {n_treasury}")
        if not args.confirm:
            db.rollback()
            print("\nDry run only. Stop the backend, then re-run with --confirm, then restart the backend.")
        else:
            print("\nDone. Restart the backend so the live order books are rebuilt from the database.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
