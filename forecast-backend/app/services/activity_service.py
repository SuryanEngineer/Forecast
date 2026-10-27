"""
A user's account activity feed: every buy and sell, dividend payout, fee, treasury move and deposit -- built from the
append-only wallet ledger (so it always reconciles with the cash balance) and enriched with player / tournament names.
Order holds and releases (zero-amount bookkeeping) are left out. Read-only.
"""
from __future__ import annotations

import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.dividend import DividendLineItem, DividendPayout
from app.models.order import Order, Trade
from app.models.player import Player
from app.models.tournament import Tournament
from app.models.wallet import LedgerEntry, LedgerEntryType, Wallet

T = LedgerEntryType

# filter name -> ledger entry types
GROUPS: dict[str, list[LedgerEntryType]] = {
    "trades": [T.TRADE_DEBIT, T.TRADE_CREDIT],
    "dividends": [T.DIVIDEND_CREDIT],
    "fees": [T.FEE],
    "treasury": [T.TREASURY_BUY, T.TREASURY_REDEEM],
    "cash": [T.DEPOSIT, T.WITHDRAWAL],
}
_HIDDEN = [T.ORDER_HOLD, T.ORDER_RELEASE]


def user_activity(db: Session, user_id: uuid.UUID, kind: str = "all", limit: int = 50, offset: int = 0) -> dict:
    wallet = db.query(Wallet).filter(Wallet.user_id == user_id).first()
    if wallet is None:
        return {"items": [], "total": 0, "next_offset": None}

    q = db.query(LedgerEntry).filter(LedgerEntry.wallet_id == wallet.id, LedgerEntry.entry_type.notin_(_HIDDEN))
    if kind in GROUPS:
        q = q.filter(LedgerEntry.entry_type.in_(GROUPS[kind]))
    total = q.with_entities(func.count(LedgerEntry.id)).scalar() or 0
    entries = q.order_by(LedgerEntry.created_at.desc(), LedgerEntry.id.desc()).offset(offset).limit(limit).all()

    trade_ids = {e.reference_id for e in entries if e.reference_type == "trade" and e.reference_id}
    payout_ids = {e.reference_id for e in entries if e.reference_type == "dividend_payout" and e.reference_id}
    fee_ref_ids = {e.reference_id for e in entries if e.entry_type == T.FEE and e.reference_id}

    trades = {t.id: t for t in db.query(Trade).filter(Trade.id.in_(trade_ids)).all()} if trade_ids else {}
    payouts = {p.id: p for p in db.query(DividendPayout).filter(DividendPayout.id.in_(payout_ids)).all()} if payout_ids else {}
    lines = (
        {li.payout_id: li for li in db.query(DividendLineItem).filter(DividendLineItem.user_id == user_id, DividendLineItem.payout_id.in_(payout_ids)).all()}
        if payout_ids else {}
    )
    fee_orders = {o.id: o for o in db.query(Order).filter(Order.id.in_(fee_ref_ids)).all()} if fee_ref_ids else {}

    player_ids = {t.player_id for t in trades.values()} | {p.player_id for p in payouts.values()} | {o.player_id for o in fee_orders.values()}
    names = {pid: tag for pid, tag in db.query(Player.id, Player.gamertag).filter(Player.id.in_(player_ids)).all()} if player_ids else {}
    tournament_ids = {p.tournament_id for p in payouts.values()}
    tournaments = {tid: n for tid, n in db.query(Tournament.id, Tournament.name).filter(Tournament.id.in_(tournament_ids)).all()} if tournament_ids else {}

    items: list[dict] = []
    for e in entries:
        item = {
            "id": e.id, "at": e.created_at, "amount": e.amount, "balance_after": e.balance_after,
            "type": e.entry_type.value, "title": "", "detail": "", "player_id": None, "gamertag": None,
            "quantity": None, "price": None,
        }
        et = e.entry_type
        if et in (T.TRADE_DEBIT, T.TRADE_CREDIT):
            t = trades.get(e.reference_id)
            buy = et == T.TRADE_DEBIT
            item["type"] = "buy" if buy else "sell"
            if t is not None:
                tag = names.get(t.player_id, "player")
                ipo = t.buy_order_id is None and t.sell_order_id is None
                item.update(player_id=t.player_id, gamertag=tag, quantity=t.quantity, price=t.price)
                item["title"] = f"{'Bought' if buy else 'Sold'} {t.quantity:,} × {tag}"
                item["detail"] = ("IPO auction · " if ipo else "") + f"{t.quantity:,} shares at ${t.price:,.2f}"
            else:
                item["title"] = "Share purchase" if buy else "Share sale"
        elif et == T.DIVIDEND_CREDIT:
            p = payouts.get(e.reference_id)
            li = lines.get(e.reference_id)
            item["type"] = "dividend"
            if p is not None:
                tag = names.get(p.player_id, "player")
                item.update(player_id=p.player_id, gamertag=tag, quantity=li.quantity_held_snapshot if li else None, price=p.per_share_amount)
                item["title"] = f"Dividend · {tag}"
                bits = [tournaments.get(p.tournament_id, "Tournament")]
                if li is not None and p.per_share_amount is not None:
                    bits.append(f"{li.quantity_held_snapshot:,} shares held at the start × ${p.per_share_amount:,.4f}")
                item["detail"] = " · ".join(bits)
            else:
                item["title"] = "Dividend"
        elif et == T.FEE:
            o = fee_orders.get(e.reference_id)
            item["type"] = "fee"
            item["title"] = e.memo or "Fee"
            if o is not None:
                tag = names.get(o.player_id)
                item.update(player_id=o.player_id, gamertag=tag)
                if tag:
                    item["detail"] = f"On your {tag} trade"
        elif et == T.TREASURY_BUY:
            item["type"], item["title"] = "treasury_buy", "Treasury purchase"
        elif et == T.TREASURY_REDEEM:
            item["type"], item["title"] = "treasury_redeem", "Treasury redemption"
        elif et == T.DEPOSIT:
            item["type"], item["title"] = "deposit", e.memo or "Deposit"
        elif et == T.WITHDRAWAL:
            item["type"], item["title"] = "withdrawal", e.memo or "Withdrawal"
        else:
            item["title"] = e.memo or et.value
        items.append(item)

    nxt = offset + limit if offset + limit < total else None
    return {"items": items, "total": total, "next_offset": nxt}
