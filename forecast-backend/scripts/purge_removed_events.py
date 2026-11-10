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
import time
from collections import defaultdict
from datetime import timezone
from decimal import Decimal

sys.path.insert(0, ".")

from sqlalchemy import or_  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402

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


def run(args, verbose: bool) -> None:
    say = print if verbose else (lambda *a, **k: None)
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
            say("Nothing to erase.")
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
        by_user_items: dict = defaultdict(list)                  # user_id -> [line_item]
        for li, _tid in rows:
            owed[li.user_id] += Decimal(str(li.amount_paid))
            by_user_items[li.user_id].append(li)

        ids = list(owed.keys()) or [None]
        wallets = {w.user_id: w for w in db.query(Wallet).filter(Wallet.user_id.in_(ids)).all()}
        names = {u.id: (getattr(u, "username", None) or u.display_name) for u in db.query(User).filter(User.id.in_(ids)).all()}

        say("Events to erase:")
        for t in tournaments:
            n_pay = db.query(DividendPayout).filter(DividendPayout.tournament_id == t.id).count()
            say(f"  - {t.start_time:%Y-%m-%d}  {t.name}  [{t.status.value}]  {n_pay} payouts")

        say("\nMoney to take back:")
        shortfalls: dict = {}
        for uid, total in owed.items():
            w = wallets.get(uid)
            free = (Decimal(str(w.cash_balance)) - Decimal(str(w.held_balance))) if w else ZERO
            short = max(ZERO, total - free)
            if short > 0:
                shortfalls[uid] = short
            flag = f"  SHORT by {_usd(short)} (already spent)" if short > 0 else ""
            if len(owed) <= 25 or short > 0:
                say(f"  - {names.get(uid, str(uid))}: {_usd(total)} (free cash {_usd(free)}){flag}")
        say(f"  total {_usd(sum(owed.values(), ZERO))} across {len(owed)} user(s)")

        like_filters = [Notification.ref_key.like(f"%{tid}%") for tid in tids]
        notif_q = db.query(Notification).filter(or_(*like_filters))
        n_notifs = notif_q.count()
        say(f"\nNotifications to delete: {n_notifs}")

        if shortfalls and not args.force_shortfall:
            say("\nSome users have already spent this money, so nothing will be changed.")
            say("Re-run with --force-shortfall to erase the records anyway and take back what their free cash allows.")
            if args.confirm:
                sys.exit(1)
            return
        if not args.confirm:
            say("\nDry run only. Re-run with --confirm to erase all of this (it cannot be undone).")
            return

        # Lock every affected wallet up front, always in the same order, so concurrent trading/snapshot jobs queue behind us
        # instead of deadlocking with us.
        wallet_ids = sorted(w.id for w in wallets.values())
        if wallet_ids:
            print("Locking wallets ...", flush=True)
            # populate_existing: re-read the locked rows so the balances used below are current (without expiring everything else)
            locked = db.query(Wallet).filter(Wallet.id.in_(wallet_ids)).order_by(Wallet.id).populate_existing().with_for_update().all()
            wallets = {w.user_id: w for w in locked}

        # ---- 1: wallets + ledger, in bulk. Every line item of one tournament is dated to the same moment, so the "later rows
        # carried this credit in their running balance" correction is one UPDATE per (wallet, moment), not one per line item.
        def chunks(seq, n=1000):
            seq = list(seq)
            for i in range(0, len(seq), n):
                yield seq[i:i + n]

        all_items = [li for uid in sorted(by_user_items.keys(), key=str) for li in by_user_items[uid]]
        print(f"\nApplying: {len(all_items)} line items across {len(owed)} users ...", flush=True)
        entry_ids = [li.ledger_entry_id for li in all_items if li.ledger_entry_id]
        entries: dict = {}
        for ch in chunks(entry_ids):
            for e in db.query(LedgerEntry).filter(LedgerEntry.id.in_(ch)).all():
                entries[e.id] = e

        groups: dict = defaultdict(lambda: ZERO)          # (wallet_id, moment) -> amount to take out of later running balances
        snap_cuts: dict = defaultdict(list)               # user_id -> [(day, amount)]
        for li in all_items:
            amt = Decimal(str(li.amount_paid))
            e = entries.get(li.ledger_entry_id) if li.ledger_entry_id else None
            when = e.created_at if e is not None else li.created_at
            if e is not None:
                groups[(e.wallet_id, e.created_at)] += amt
            snap_cuts[li.user_id].append((when.astimezone(timezone.utc).strftime("%Y-%m-%d"), amt))
        for i, ((wid, moment), amt) in enumerate(sorted(groups.items(), key=lambda kv: (str(kv[0][0]), kv[0][1])), 1):
            db.query(LedgerEntry).filter(LedgerEntry.wallet_id == wid, LedgerEntry.created_at >= moment).update(
                {LedgerEntry.balance_after: LedgerEntry.balance_after - amt}, synchronize_session=False
            )
            if i % 50 == 0:
                print(f"  ledger running balances fixed for {i}/{len(groups)} (wallet, date) groups", flush=True)
        print("  deleting line items and their ledger entries ...", flush=True)
        for ch in chunks(li.id for li in all_items):
            db.query(DividendLineItem).filter(DividendLineItem.id.in_(ch)).delete(synchronize_session=False)
        for ch in chunks(entries.keys()):
            db.query(LedgerEntry).filter(LedgerEntry.id.in_(ch)).delete(synchronize_session=False)

        unrecovered = ZERO
        for uid in sorted(owed.keys(), key=str):
            w = wallets.get(uid)
            if w is not None:
                free = Decimal(str(w.cash_balance)) - Decimal(str(w.held_balance))
                take = min(owed[uid], max(ZERO, free))
                w.cash_balance = Decimal(str(w.cash_balance)) - take
                unrecovered += owed[uid] - take
        db.flush()
        print("  wallets debited", flush=True)

        # ---- 2: payouts, 3: notifications
        db.query(DividendPayout).filter(DividendPayout.tournament_id.in_(tids)).delete(synchronize_session=False)
        notif_q.delete(synchronize_session=False)

        # ---- 4: daily snapshots from the payout day on included the credit. Done last, in one fixed (id) order, with the rows
        # locked first: the live snapshot job writes the same table.
        if snap_cuts:
            print("  adjusting daily portfolio snapshots ...", flush=True)
            snaps = (
                db.query(PortfolioSnapshot)
                .filter(PortfolioSnapshot.user_id.in_(list(snap_cuts.keys())))
                .order_by(PortfolioSnapshot.id)
                .with_for_update()
                .all()
            )
            for snap in snaps:
                cut = sum((a for d, a in snap_cuts[snap.user_id] if snap.day >= d), ZERO)
                if cut:
                    snap.net_worth = max(ZERO, Decimal(str(snap.net_worth)) - cut)
                    snap.cash = max(ZERO, Decimal(str(snap.cash)) - cut)
            db.flush()

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


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--force-shortfall", action="store_true")
    args = ap.parse_args()
    # The live backend writes the same tables while this runs; if the database picks us as the loser of a deadlock the whole
    # transaction is rolled back untouched, so simply try again.
    for attempt in range(1, 8):
        try:
            run(args, verbose=(attempt == 1))
            return
        except OperationalError as exc:
            if "deadlock" not in str(exc).lower() or attempt == 7:
                raise
            print(f"\n(database deadlock with a live job -- nothing was changed; retrying, attempt {attempt + 1})")
            time.sleep(2 * attempt)


if __name__ == "__main__":
    main()
