#!/usr/bin/env python3
"""
Set the transaction fee (platform parameter fees.transaction_fee_pct) and tell every real user about it.

The fee is charged to the TAKER of each trade (instant orders and limit orders that fill straight away); a limit order that
rests and is filled by someone else pays nothing. Resting buy orders were reserved with the OLD rate, so the hold sweep
(order_service.reconcile_holds) releases the small excess on its own after a few minutes.

Dry run by default (changes nothing):
    cd forecast-backend
    python scripts/set_transaction_fee.py

Apply it (sets the fee to 0.1% and sends one notification to every real user; safe to run again, nobody is told twice):
    python scripts/set_transaction_fee.py --confirm

Another rate:
    python scripts/set_transaction_fee.py --fee 0.0015 --confirm
"""
from __future__ import annotations

import argparse
import sys
from decimal import Decimal

sys.path.insert(0, ".")

from app.db.session import SessionLocal  # noqa: E402
import app.models  # noqa: E402,F401
from app.models.bot import BotProfile  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services import economic_params_service as eps, notification_service  # noqa: E402
from app.services.house_account import HOUSE_ACCOUNT_EMAIL  # noqa: E402

KEY = "fees.transaction_fee_pct"


def pct(x: Decimal | float) -> str:
    return f"{float(x) * 100:.4g}%"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fee", type=float, default=0.001, help="New fee as a fraction (0.001 = 0.1%%).")
    ap.add_argument("--was", type=float, default=0.0025, help="The previous fee, used in the message when the stored fee already equals the new one (the deploy migrates an untouched 0.25%% row by itself).")
    ap.add_argument("--confirm", action="store_true", help="Write the change and send the notifications (otherwise a dry run).")
    args = ap.parse_args()
    if not (0 <= args.fee < 0.05):
        ap.error("--fee must be a fraction between 0 and 0.05 (0.001 = 0.1%)")
    new = Decimal(str(args.fee))

    db = SessionLocal()
    try:
        stored = eps.get_param(db, KEY)
        old = stored if stored != new else Decimal(str(args.was))
        bots = {uid for (uid,) in db.query(BotProfile.user_id).all()}
        people = [
            u for (u,) in db.query(User.id)
            .filter(User.is_active.is_(True), User.email != HOUSE_ACCOUNT_EMAIL, ~User.email.ilike("%@test.local"))
            .all() if u not in bots
        ]
        print(f"transaction fee stored now: {pct(stored)}  ->  {pct(new)}")
        print(f"real users who would be notified: {len(people)}")

        title = f"Trading fee lowered to {pct(new)}"
        body = (f"The transaction fee on instant trades is now {pct(new)} (it was {pct(old)}). "
                f"A limit order that rests and is filled by someone else still pays no fee.")
        print(f"\nnotification:\n   {title}\n   {body}")

        if not args.confirm:
            db.rollback()
            print("\nDRY RUN -- nothing was changed. Add --confirm to apply.")
            return

        eps.set_param(db, KEY, new)
        sent = notification_service.announce_to_all(db, title, body, ref_key=f"announce:fee:{new}", data={"fee": float(new), "previous": float(old)})
        db.commit()
        print(f"\nSaved. Fee is {pct(new)}; {sent} user(s) notified.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
