"""
Daily portfolio snapshots + lifetime stats for the Stats page.

Definitions (all from the append-only ledger / trade tables, so they can't drift):
  contributed capital  = deposits - withdrawals (the starting balance + any admin top-ups)
  total change         = net worth now - contributed capital          (and % of contributed capital)
  dividend earnings    = sum of DIVIDEND_CREDIT ledger entries
  interest earnings    = sum of treasury accrual log amounts
  fees paid            = sum of FEE debits
  trading earnings     = total change - dividends - interest + fees   (i.e. P&L from buying/selling, before fees)
  best/worst day       = largest day-over-day net-worth gain/loss from daily snapshots (UTC days)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.account import PortfolioSnapshot, UserSession
from app.models.order import Trade
from app.models.player import Player, Position
from app.models.treasury import TreasuryAccrualLog, TreasuryHolding
from app.models.user import User
from app.models.wallet import LedgerEntry, LedgerEntryType, Wallet
from app.services import portfolio_service, season_service

ZERO = Decimal("0")


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def snapshot_all(db: Session, day: str | None = None) -> int:
    """Upsert today's net-worth snapshot for every eligible user (the last run of the day wins)."""
    day = day or _today()
    worths = portfolio_service.compute_net_worths(db)
    existing = {s.user_id: s for s in db.query(PortfolioSnapshot).filter(PortfolioSnapshot.day == day).all()}
    for uid, w in worths.items():
        row = existing.get(uid)
        if row is None:
            db.add(PortfolioSnapshot(id=uuid.uuid4(), user_id=uid, day=day, net_worth=w["net_worth"], cash=w["cash"],
                                     holdings_value=w["holdings"] + w["treasury"]))
        else:
            row.net_worth, row.cash, row.holdings_value = w["net_worth"], w["cash"], w["holdings"] + w["treasury"]
    db.flush()
    return len(worths)


def _f(x: Decimal | None) -> float:
    return float(x or ZERO)


def user_stats(db: Session, user: User) -> dict:
    uid = user.id
    wallet = db.query(Wallet).filter(Wallet.user_id == uid).one_or_none()
    wallet_id = wallet.id if wallet else None
    w = portfolio_service.compute_net_worths(db, [uid]).get(uid, {"cash": ZERO, "holdings": ZERO, "treasury": ZERO, "net_worth": ZERO})
    net_worth = w["net_worth"]

    def ledger_sum(*types: LedgerEntryType, sign: int | None = None) -> Decimal:
        if wallet_id is None:
            return ZERO
        q = db.query(func.coalesce(func.sum(LedgerEntry.amount), 0)).filter(
            LedgerEntry.wallet_id == wallet_id, LedgerEntry.entry_type.in_(list(types)))
        if sign == -1:
            q = q.filter(LedgerEntry.amount < 0)
        return Decimal(str(q.scalar() or 0))

    deposits = ledger_sum(LedgerEntryType.DEPOSIT)
    withdrawals = ledger_sum(LedgerEntryType.WITHDRAWAL)  # stored signed (negative)
    contributed = deposits + withdrawals
    dividends = ledger_sum(LedgerEntryType.DIVIDEND_CREDIT)
    fees = -ledger_sum(LedgerEntryType.FEE, sign=-1)
    interest = Decimal(str(
        db.query(func.coalesce(func.sum(TreasuryAccrualLog.amount), 0))
        .join(TreasuryHolding, TreasuryHolding.id == TreasuryAccrualLog.holding_id)
        .filter(TreasuryHolding.user_id == uid).scalar() or 0
    ))
    total_change = net_worth - contributed
    total_change_pct = float(total_change / contributed * 100) if contributed > 0 else 0.0
    trading_earnings = total_change - dividends - interest + fees

    payout_count = (
        db.query(func.count(LedgerEntry.id))
        .filter(LedgerEntry.wallet_id == wallet_id, LedgerEntry.entry_type == LedgerEntryType.DIVIDEND_CREDIT).scalar()
        if wallet_id else 0
    )

    mine = or_(Trade.buyer_user_id == uid, Trade.seller_user_id == uid)
    trades = db.query(Trade).filter(mine).all()
    buys = sum(1 for t in trades if t.buyer_user_id == uid)
    sells = sum(1 for t in trades if t.seller_user_id == uid)
    volume = sum((t.price * t.quantity for t in trades), ZERO)
    biggest = max(trades, key=lambda t: t.price * t.quantity, default=None)
    biggest_info = None
    if biggest is not None:
        p = db.get(Player, biggest.player_id)
        biggest_info = {
            "player_id": biggest.player_id, "gamertag": p.gamertag if p else "Unknown",
            "side": "buy" if biggest.buyer_user_id == uid else "sell", "quantity": biggest.quantity,
            "price": _f(biggest.price), "value": _f(biggest.price * biggest.quantity), "executed_at": biggest.executed_at,
        }

    snaps = db.query(PortfolioSnapshot).filter(PortfolioSnapshot.user_id == uid).order_by(PortfolioSnapshot.day.asc()).all()
    best_day = worst_day = None
    for prev, cur in zip(snaps, snaps[1:]):
        delta = cur.net_worth - prev.net_worth
        pct = float(delta / prev.net_worth * 100) if prev.net_worth > 0 else 0.0
        entry = {"day": cur.day, "change": float(delta), "change_pct": pct}
        if best_day is None or delta > Decimal(str(best_day["change"])):
            best_day = entry
        if worst_day is None or delta < Decimal(str(worst_day["change"])):
            worst_day = entry
    if best_day and best_day["change"] <= 0:
        best_day = None
    if worst_day and worst_day["change"] >= 0:
        worst_day = None

    # Best / worst current holding by unrealized P&L
    holdings = []
    for pos, player in (
        db.query(Position, Player).join(Player, Player.id == Position.player_id)
        .filter(Position.user_id == uid, Position.quantity > 0).all()
    ):
        holdings.append((pos, player))
    prices = portfolio_service.last_prices(db) if holdings else {}
    pnl = []
    for pos, player in holdings:
        price = prices.get(player.id, ZERO)
        pnl.append({"player_id": player.id, "gamertag": player.gamertag, "unrealized": _f((price - pos.average_cost) * pos.quantity),
                    "pct": float((price - pos.average_cost) / pos.average_cost * 100) if pos.average_cost > 0 else 0.0})
    best_holding = max(pnl, key=lambda r: r["unrealized"], default=None)
    worst_holding = min(pnl, key=lambda r: r["unrealized"], default=None)

    sess = db.query(func.count(UserSession.id), func.coalesce(func.sum(UserSession.active_seconds), 0)).filter(UserSession.user_id == uid).one()

    season = season_service.get_active_season(db)
    season_info = None
    if season is not None:
        for r in season_service.season_standings(db, season):
            if r["user_id"] == uid:
                season_info = {**r, **season_service.rank_progress(r["season_points"]), "season_name": season.name,
                               "ends_at": season.ends_at, "season_id": season.id}
                break

    return {
        "net_worth": _f(net_worth), "cash": _f(w["cash"]), "holdings_value": _f(w["holdings"]), "treasury_value": _f(w["treasury"]),
        "contributed_capital": _f(contributed),
        "total_change": _f(total_change), "total_change_pct": total_change_pct,
        "dividend_earnings": _f(dividends), "dividend_payouts": int(payout_count or 0),
        "interest_earnings": _f(interest), "fees_paid": _f(fees), "trading_earnings": _f(trading_earnings),
        "total_trades": len(trades), "buy_trades": buys, "sell_trades": sells, "trade_volume": _f(volume),
        "biggest_trade": biggest_info, "best_day": best_day, "worst_day": worst_day,
        "best_holding": best_holding, "worst_holding": worst_holding,
        "member_since": user.created_at, "sessions": int(sess[0] or 0), "minutes_on_site": round(int(sess[1] or 0) / 60),
        "season": season_info, "season_history": season_service.user_season_history(db, uid),
        "history": [{"day": s.day, "net_worth": _f(s.net_worth)} for s in snaps[-120:]],
    }
