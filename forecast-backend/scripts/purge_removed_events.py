#!/usr/bin/env python3
"""
Completely erase the removed events (the Arenas Cash Cup / Arenas Test Cup family): the money, the notifications, every record.

For every matching tournament it:
  1. takes each shareholder's dividend back out of their wallet and deletes the ledger entries that credited it (later ledger
     rows have the amount taken out of their running balance, so the wallet still adds up to its ledger);
  2. deletes the dividend line items + payouts;
  3. deletes the notifications about the event (dividend paid, started, ended, game wins);
  4. takes the amount back out of the users' daily portfolio snapshots from the payout day on (net worth + cash), so charts,
     best/worst day and lifetime stats no longer show it;
  5. deletes the tournament itself, which cascades to its results, archive, entrants, qualifier rows and Osirion mapping.

A user who has already SPENT the money (not enough free cash to take it back) blocks the run: the script lists them and does
nothing. Re-run with --force-shortfall to erase the records anyway and take back as much as their free cash allows (the
unrecovered amount is printed; their wallet then holds slightly more than their ledger shows).

    python scripts/purge_removed_events.py                    # dry run
    python scripts/purge_removed_events.py --confirm
    python scripts/purge_removed_events.py --confirm --force-shortfall

Not touched: share prices (they re-rate from the remaining results on the next reprice) and closed seasons' stored finals.
Back up (or be sure about) the database first: this deletes rows for good.
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from decimal import Decimal

sys.path.insert(0, ".")

from sqlalchemy import or_  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.engine import tracking_policy  # noqa: E402
from app.models.account import PortfolioSnapshot  # noqa: E402
from app.models.dividend import DividendLineItem, DividendPayout  # noqa: E402
from app.models.notification import Notification  # noqa: E402
from app.models.osirion import OsirionTournamentMapping  # noqa: E402
from app.models.tournament import Tournament  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.wallet import LedgerEntry, Wallet  # noqa: E402

ZERO = Decimal("0")


def _usd(x) -> str:
    return f"${Decimal(str(x)):,.2f}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--force-shortfall", action="store_true")
    args = ap.parse_args()
    db = SessionLocal()
    try:
        mappings = {m.tournament_id: m for m in db.query(OsirionTournamentMapping).all()}
        tournaments = []
        for t in db.query(Tournament).all():
            m = mappings.get(t.id)
            text = f"{t.name} {m.osirion_event_id if m else ''} {m.osirion_display_name if m and m.osirion_display_name else ''}"
            if tracking_policy.is_hidden_family(text):
                tournaments.append(t)
        if not tournaments:
            print("Nothing to erase.")
            return
        tournaments.sort(key=lambda x: x.start_time or x.created_at)
        tids = [t.id for t in tournaments]

        # ---- what was paid, per user
        rows = (
            db.query(DividendLineItem, DividendPayout.tournament_id)
            .join(DividendPayout, DividendPayout.id == DividendLineItem.payout_id)
            .filter(DividendPayout.tournament_id.in_(tids))
            .all()
        )
        owed: dict = defaultdict(lambda: ZERO)                  # user_id -> total to take back
        by_user_items: dict = defaultdict(list)                  # user_id -> [(line_item, amount)]
        for li, _tid in rows:
            amt = Decimal(str(li.amount_paid))
            owed[li.user_id] += amt
            by_user_items[li.user_id].append(li)

        wallets = {w.user_id: w for w in db.query(Wallet).filter(Wallet.user_id.in_(list(owed.keys()) or [None])).all()}
        names = {u.id: (getattr(u, "username", None) or u.display_name) for u in db.query(User).filter(User.id.in_(list(owed.keys()) or [None])).all()}

        print("Events to erase:")
        for t in tournaments:
            n_pay = db.query(DividendPayout).filter(DividendPayout.tournament_id == t.id).count()
            print(f"  - {t.start_time:%Y-%m-%d}  {t.name}  [{t.status.value}]  {n_pay} payouts")

        print("\nMoney to take back:")
        shortfalls: dict = {}
        for uid, total in owed.items():
            w = wallets.get(uid)
            free = (Decimal(str(w.cash_balance)) - Decimal(str(w.held_balance))) if w else ZERO
            short = max(ZERO, total - free)
            if short > 0:
                shortfalls[uid] = short
            flag = f"  SHORT by {_usd(short)} (already spent)" if short > 0 else ""
            print(f"  - {names.get(uid, str(uid))}: {_usd(total)} (free cash {_usd(free)}){flag}")
        print(f"  total {_usd(sum(owed.values(), ZERO))} across {len(owed)} user(s)")

        like_filters = [Notification.ref_key.like(f"%{tid}%") for tid in tids]
        notif_q = db.query(Notification).filter(or_(*like_filters))
        n_notifs = notif_q.count()
        print(f"\nNotifications to delete: {n_notifs}")

        if shortfalls and not args.force_shortfall:
            print("\nSome users have already spent this money, so nothing will be changed.")
            print("Re-run with --force-shortfall to erase the records anyway and take back what their free cash allows.")
            if args.confirm:
                sys.exit(1)
            return
        if not args.confirm:
            print("\nDry run only. Re-run with --confirm to erase all of this (it cannot be undone).")
            return

        # ---- 1+4: wallets, ledger, snapshots
        unrecovered = ZERO
        for uid, items in by_user_items.items():
            w = wallets.get(uid)
            for li in items:
                amt = Decimal(str(li.amount_paid))
                entry = db.get(LedgerEntry, li.ledger_entry_id) if li.ledger_entry_id else None
                when = entry.created_at if entry is not None else li.created_at
                if entry is not None:
                    # later rows carried this credit in their running balance
                    db.query(LedgerEntry).filter(
                        LedgerEntry.wallet_id == entry.wallet_id, LedgerEntry.id != entry.id, LedgerEntry.created_at >= entry.created_at
                    ).update({LedgerEntry.balance_after: LedgerEntry.balance_after - amt}, synchronize_session=False)
                # the daily snapshots from that day on included it
                day = when.astimezone(__import__("datetime").timezone.utc).strftime("%Y-%m-%d")
                for snap in db.query(PortfolioSnapshot).filter(PortfolioSnapshot.user_id == uid, PortfolioSnapshot.day >= day).all():
                    snap.net_worth = max(ZERO, Decimal(str(snap.net_worth)) - amt)
                    snap.cash = max(ZERO, Decimal(str(snap.cash)) - amt)
                # the line item points at the ledger row, so it goes first
                db.delete(li)
                db.flush()
                if entry is not None:
                    db.delete(entry)
                    db.flush()
            if w is not None:
                free = Decimal(str(w.cash_balance)) - Decimal(str(w.held_balance))
                take = min(owed[uid], max(ZERO, free))
                w.cash_balance = Decimal(str(w.cash_balance)) - take
                unrecovered += owed[uid] - take

        # ---- 2: payouts
        db.query(DividendPayout).filter(DividendPayout.tournament_id.in_(tids)).delete(synchronize_session=False)
        # ---- 3: notifications
        notif_q.delete(synchronize_session=False)
        # ---- 5: the tournaments (DB-level cascade removes results, archive, entrants, qualifier rows, Osirion mapping)
        db.query(Tournament).filter(Tournament.id.in_(tids)).delete(synchronize_session=False)
        db.commit()
        print(f"\nDone: erased {len(tournaments)} events, took back {_usd(sum(owed.values(), ZERO) - unrecovered)}, deleted {n_notifs} notifications.")
        if unrecovered > 0:
            print(f"Could not take back {_usd(unrecovered)} (already spent); those wallets hold that much more than their ledger shows.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
