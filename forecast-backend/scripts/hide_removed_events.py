#!/usr/bin/env python3
"""
Hide events the product no longer shows (the Arenas Cash Cup and its Arenas Test Cup rounds) from every list and calendar.

It marks each matching tournament as an archive row (the same flag historical backfills use), which keeps it out of the public
tournament list, calendar and live views and out of the background sync. It does NOT touch money: dividends already paid for
these events stay in users' wallets, ledgers and history (it prints how much, so you can decide separately).

    python scripts/hide_removed_events.py            # dry run
    python scripts/hide_removed_events.py --confirm
"""
from __future__ import annotations

import argparse
import sys

sys.path.insert(0, ".")

from sqlalchemy import func  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.engine import tracking_policy  # noqa: E402
from app.models.dividend import DividendLineItem, DividendPayout  # noqa: E402
from app.models.osirion import OsirionTournamentMapping  # noqa: E402
from app.models.tournament import Tournament  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--confirm", action="store_true")
    args = ap.parse_args()
    db = SessionLocal()
    try:
        mappings = {m.tournament_id: m for m in db.query(OsirionTournamentMapping).all()}
        rows = []
        for t in db.query(Tournament).all():
            m = mappings.get(t.id)
            text = f"{t.name} {m.osirion_event_id if m else ''} {m.osirion_display_name if m and m.osirion_display_name else ''}"
            if tracking_policy.is_hidden_family(text):
                rows.append(t)
        if not rows:
            print("Nothing to hide.")
            return
        total_paid = 0.0
        for t in sorted(rows, key=lambda x: x.start_time or x.created_at):
            paid = (
                db.query(func.coalesce(func.sum(DividendLineItem.amount_paid), 0))
                .join(DividendPayout, DividendPayout.id == DividendLineItem.payout_id)
                .filter(DividendPayout.tournament_id == t.id)
                .scalar()
            )
            total_paid += float(paid)
            state = "already hidden" if t.is_historical_archive else ("-> hiding" if args.confirm else "-> would hide")
            print(f"  - {t.start_time:%Y-%m-%d}  {t.name}  [{t.status.value}]  dividends paid ${float(paid):,.2f}  {state}")
            if args.confirm:
                t.is_historical_archive = True
        print(f"\nDividends already paid for these events: ${total_paid:,.2f} (left in users' wallets; this script never reverses money).")
        if args.confirm:
            db.commit()
            print("Done.")
        else:
            print("Dry run only. Re-run with --confirm to hide them.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
