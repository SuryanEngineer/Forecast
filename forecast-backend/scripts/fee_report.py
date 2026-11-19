#!/usr/bin/env python3
"""
How much money have transaction fees taken out of players' pockets, and where did it go? Read-only.

Every fee is a pair of ledger rows (see wallet_service.charge_fee / receive_fee_revenue): the taker pays it (a negative FEE
row) and the House receives it (a positive FEE row). So fees leave human + bot wallets but are NOT destroyed -- they sit in the
House's cash, which pays for buying shares back from sellers. Old bot / House rows are rolled up into one summed row per
wallet (retention_service), so all-time totals stay exact; the 24h / 7d / 30d windows ignore those rolled-up rows and are
therefore a slight undercount for bots.

Usage (from forecast-backend, venv active):
    python scripts/fee_report.py
"""
from __future__ import annotations

import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")

from sqlalchemy import func  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
import app.models  # noqa: E402,F401
from app.models.bot import BotProfile  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.wallet import LedgerEntry, LedgerEntryType, Wallet  # noqa: E402
from app.services.house_account import HOUSE_ACCOUNT_EMAIL  # noqa: E402


def money(x: float) -> str:
    return f"${x:,.2f}"


def main() -> None:
    db = SessionLocal()
    try:
        house_id = db.query(User.id).filter(User.email == HOUSE_ACCOUNT_EMAIL).scalar()
        bot_ids = {uid for (uid,) in db.query(BotProfile.user_id).all()}
        # scripts/smoke_test.py creates *@test.local accounts (and has them join auctions); they are not real players.
        test_ids = {uid for (uid,) in db.query(User.id).filter(User.email.ilike("%@test.local")).all()}

        def group(uid):
            return "house" if uid == house_id else "bot" if uid in bot_ids else "test" if uid in test_ids else "human"

        def total(entry_type, negative: bool, since: datetime | None = None, memo_like: str | None = None, memo_not_like: str | None = None):
            q = (
                db.query(Wallet.user_id, func.coalesce(func.sum(LedgerEntry.amount), 0), func.count(LedgerEntry.id))
                .join(Wallet, Wallet.id == LedgerEntry.wallet_id)
                .filter(LedgerEntry.entry_type == entry_type, LedgerEntry.amount < 0 if negative else LedgerEntry.amount > 0)
            )
            if since is not None:
                q = q.filter(LedgerEntry.created_at >= since, func.coalesce(LedgerEntry.reference_type, "") != "rollup")
            if memo_like:
                q = q.filter(LedgerEntry.memo.ilike(memo_like))
            if memo_not_like:
                q = q.filter(~func.coalesce(LedgerEntry.memo, "").ilike(memo_not_like))
            out, n = defaultdict(float), defaultdict(int)
            for uid, s, c in q.group_by(Wallet.user_id).all():
                out[group(uid)] += abs(float(s))
                n[group(uid)] += int(c)
            return out, n

        now = datetime.now(timezone.utc)
        print("=" * 72)
        paid, n = total(LedgerEntryType.FEE, True)
        got, _ = total(LedgerEntryType.FEE, False)
        print("ALL-TIME FEES PAID (taker side)")
        for g in ("human", "bot", "house", "test"):
            note = "   <- smoke-test accounts (@test.local), NOT real players" if g == "test" else ""
            print(f"   {g:<6} {money(paid[g]):>20}   ({n[g]:,} ledger rows, rolled-up rows count as one){note}")
        player_paid = paid["human"] + paid["bot"]
        print(f"   real humans + bots together: {money(player_paid)}")
        print(f"   received by the House:  {money(got['house'])}   (kept in the House's cash, not destroyed)")

        h_trade, _ = total(LedgerEntryType.FEE, True, memo_like="%Transaction fee%")
        h_other, _ = total(LedgerEntryType.FEE, True, memo_not_like="%Transaction fee%")
        print(f"\nreal humans: trading fees {money(h_trade['human'])}, other fees {money(h_other['human'])}")
        print(f"test accounts: trading fees {money(h_trade['test'])}, other fees (auction entry) {money(h_other['test'])}")

        # Fees that are not trading fees (the only other writer is the auction entry fee): who paid, when, and the matching rounds.
        odd = (
            db.query(User.email, User.display_name, LedgerEntry.amount, LedgerEntry.memo, LedgerEntry.reference_type, LedgerEntry.created_at)
            .join(Wallet, Wallet.id == LedgerEntry.wallet_id)
            .join(User, User.id == Wallet.user_id)
            .filter(LedgerEntry.entry_type == LedgerEntryType.FEE, ~func.coalesce(LedgerEntry.memo, "").ilike("%Transaction fee%"))
            .order_by(LedgerEntry.created_at)
            .limit(40)
            .all()
        )
        from app.models.auction import AuctionParticipant, AuctionRound

        print(f"\nNON-TRADING FEE ROWS ({len(odd)} shown, oldest first); auction rounds in the database: {db.query(AuctionRound).count()}, auction entries: {db.query(AuctionParticipant).count()}")
        for email, username, amount, memo, ref, at in odd:
            print(f"   {at:%Y-%m-%d %H:%M}  {float(amount):>12,.2f}  {username or email}  [{memo or ''}] ({ref or ''})")

        print("\nRECENT WINDOWS (humans + bots)")
        for label, days in (("last 24 hours", 1), ("last 7 days", 7), ("last 30 days", 30)):
            w, _ = total(LedgerEntryType.FEE, True, since=now - timedelta(days=days))
            print(f"   {label:<14} humans {money(w['human']):>16}   bots {money(w['bot']):>16}")

        div, _ = total(LedgerEntryType.DIVIDEND_CREDIT, False)
        print("\nFOR SCALE")
        print(f"   dividends paid to humans + bots, all-time: {money(div['human'] + div['bot'])}")
        print(f"   dividends paid to the House, all-time:     {money(div['house'])}")
        if div["human"] + div["bot"] > 0:
            print(f"   fees taken back from players = {player_paid / (div['human'] + div['bot']) * 100:.1f}% of the dividends they received")
        print("=" * 72)
    finally:
        db.close()


if __name__ == "__main__":
    main()
