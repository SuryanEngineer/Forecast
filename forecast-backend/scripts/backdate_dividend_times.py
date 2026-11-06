#!/usr/bin/env python3
"""
Re-date dividends that were already paid so they sit at the moment their tournament FINISHED (Tournament.end_time)
instead of when the payout job ran. "Finished" = the end of the last game played in it (falling back to the
tournament's end time), since a tracked window can stay open long after the final game. New payouts are dated this way automatically (dividend_service.process_payout);
this fixes the ones paid before that change (e.g. a retroactive payout run long after the event).

Only moves a dividend EARLIER, never later. Touches the wallet
ledger entry's timestamp and the dividend line item's; no balances change. Dry run by default.

    python3 scripts/backdate_dividend_times.py
    python3 scripts/backdate_dividend_times.py --confirm
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

sys.path.insert(0, ".")

from app.db.session import SessionLocal  # noqa: E402
from app.models.dividend import DividendLineItem, DividendPayout  # noqa: E402
from app.models.tournament import Tournament  # noqa: E402
from app.models.wallet import LedgerEntry  # noqa: E402
from app.services import dividend_service  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--confirm", action="store_true")
    args = ap.parse_args()
    now = datetime.now(timezone.utc)

    def aware(dt):
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    db = SessionLocal()
    try:
        rows = (
            db.query(DividendLineItem, LedgerEntry, Tournament)
            .join(DividendPayout, DividendPayout.id == DividendLineItem.payout_id)
            .join(Tournament, Tournament.id == DividendPayout.tournament_id)
            .join(LedgerEntry, LedgerEntry.id == DividendLineItem.ledger_entry_id)
            .all()
        )
        finished: dict = {}
        moved = 0
        per_tournament: dict[str, int] = {}
        for item, entry, t in rows:
            if t.id not in finished:
                finished[t.id] = dividend_service.tournament_finished_at(db, t)
            end = aware(finished[t.id])
            if end > now or aware(entry.created_at) <= end:
                continue
            moved += 1
            per_tournament[t.name] = per_tournament.get(t.name, 0) + 1
            if args.confirm:
                entry.created_at = end
                item.created_at = end
        for name, n in sorted(per_tournament.items()):
            print(f"  {n:>5} dividend(s) -> end of {name}")
        print(f"\n{moved} dividend(s) {'re-dated' if args.confirm else 'would be re-dated'}.")
        if args.confirm:
            db.commit()
        else:
            print("Dry run only. Re-run with --confirm to apply.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
