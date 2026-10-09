#!/usr/bin/env python3
"""
Set the economy knobs that were changed in code defaults (existing databases keep their OLD stored values until updated):

    wallet.starting_balance  -> 10000   (cash every NEW user receives; existing users' wallets are not touched)
    auction.entry_fee        -> 100     (1% of the starting balance, same ratio as the original $10k on $1M)

    python3 scripts/set_economy_params.py            # dry run: shows current -> new
    python3 scripts/set_economy_params.py --confirm
    python3 scripts/set_economy_params.py --confirm --set wallet.starting_balance=25000   # any other key=value
"""
from __future__ import annotations

import argparse
import sys
from decimal import Decimal

sys.path.insert(0, ".")

from app.db.session import SessionLocal  # noqa: E402
from app.services import economic_params_service  # noqa: E402

WANTED = {"wallet.starting_balance": Decimal("10000"), "auction.entry_fee": Decimal("100")}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    args = ap.parse_args()
    wanted = dict(WANTED)
    for kv in args.set:
        k, v = kv.split("=", 1)
        wanted[k.strip()] = Decimal(v.strip())
    db = SessionLocal()
    try:
        for k, v in wanted.items():
            cur = economic_params_service.get_param(db, k)
            print(f"{k:<28} {cur} -> {v}" + ("   (no change)" if cur == v else ""))
            if args.confirm and cur != v:
                economic_params_service.set_param(db, k, v)
        if args.confirm:
            db.commit()
            print("\nSaved. New accounts now start with the new balance; existing accounts keep their current cash.")
        else:
            db.rollback()
            print("\nDry run only. Re-run with --confirm.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
