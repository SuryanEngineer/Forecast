"""
Product analytics over real (non-bot, non-House) accounts. Used by scripts/user_analytics.py and the admin API.
Everything is computed from tables we already keep: users, user_sessions (heartbeats), trades, ledger entries,
portfolio snapshots and season entries -- no third-party tracker needed.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.account import UserSession
from app.models.bot import BotProfile
from app.models.order import Order, Trade
from app.models.user import User
from app.models.wallet import LedgerEntry, LedgerEntryType, Wallet
from app.services import portfolio_service, season_service
from app.services.house_account import HOUSE_ACCOUNT_EMAIL

ZERO = Decimal("0")


def _aware(dt):
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def real_users(db: Session) -> list[User]:
    return (
        db.query(User)
        .filter(User.email != HOUSE_ACCOUNT_EMAIL, User.id.notin_(select(BotProfile.user_id)))
        .order_by(User.created_at.asc()).all()
    )


def user_table(db: Session) -> list[dict]:
    users = real_users(db)
    ids = [u.id for u in users]
    if not ids:
        return []

    sess = {uid: (n, secs, first, last) for uid, n, secs, first, last in db.query(
        UserSession.user_id, func.count(UserSession.id), func.coalesce(func.sum(UserSession.active_seconds), 0),
        func.min(UserSession.started_at), func.max(UserSession.last_seen_at)).group_by(UserSession.user_id).all()}

    trades_n: dict = defaultdict(int)
    volume: dict = defaultdict(lambda: ZERO)
    biggest: dict = defaultdict(lambda: ZERO)
    for t in db.query(Trade.buyer_user_id, Trade.seller_user_id, Trade.price, Trade.quantity).all():
        val = t.price * t.quantity
        for uid in {t.buyer_user_id, t.seller_user_id}:
            if uid is not None:
                trades_n[uid] += 1
                volume[uid] += val
                biggest[uid] = max(biggest[uid], val)

    orders_n = {uid: n for uid, n in db.query(Order.user_id, func.count(Order.id)).group_by(Order.user_id).all()}

    wallet_by_user = {uid: wid for uid, wid in db.query(Wallet.user_id, Wallet.id).all()}
    ledger: dict = defaultdict(lambda: defaultdict(lambda: ZERO))
    for wid, etype, total in db.query(LedgerEntry.wallet_id, LedgerEntry.entry_type, func.sum(LedgerEntry.amount)).group_by(
            LedgerEntry.wallet_id, LedgerEntry.entry_type).all():
        ledger[wid][etype] = total or ZERO

    worths = portfolio_service.compute_net_worths(db, ids)
    season = season_service.get_active_season(db)
    standings = {r["user_id"]: r for r in season_service.season_standings(db, season)} if season else {}

    rows = []
    for u in users:
        n, secs, first, last = sess.get(u.id, (0, 0, None, None))
        led = ledger.get(wallet_by_user.get(u.id), {})
        contributed = led.get(LedgerEntryType.DEPOSIT, ZERO) + led.get(LedgerEntryType.WITHDRAWAL, ZERO)
        nw = worths.get(u.id, {}).get("net_worth", ZERO)
        st = standings.get(u.id)
        rows.append({
            "email": u.email, "username": u.display_name, "created_at": _aware(u.created_at),
            "email_verified": u.email_verified_at is not None, "active": u.is_active,
            "last_login": _aware(u.last_login_at), "last_seen": _aware(u.last_seen_at or last),
            "logins": u.login_count or 0, "sessions": n, "minutes_on_site": round(int(secs) / 60, 1),
            "avg_session_min": round(int(secs) / 60 / n, 1) if n else 0.0,
            "orders": orders_n.get(u.id, 0), "trades": trades_n.get(u.id, 0),
            "trade_volume": float(volume.get(u.id, ZERO)), "biggest_trade": float(biggest.get(u.id, ZERO)),
            "dividends": float(led.get(LedgerEntryType.DIVIDEND_CREDIT, ZERO)),
            "fees_paid": float(-min(ZERO, led.get(LedgerEntryType.FEE, ZERO))),
            "net_worth": float(nw), "return_pct": float((nw - contributed) / contributed * 100) if contributed > 0 else 0.0,
            "season_points": st["season_points"] if st else 0, "season_rank": st["rank_tier"] if st else "",
        })
    return rows


def kpis(db: Session, rows: list[dict] | None = None) -> dict:
    rows = rows if rows is not None else user_table(db)
    now = datetime.now(timezone.utc)
    total = len(rows)

    def within(dt, days):
        return dt is not None and (now - dt) <= timedelta(days=days)

    seen = lambda days: sum(1 for r in rows if within(r["last_seen"], days))  # noqa: E731
    signups = lambda days: sum(1 for r in rows if within(r["created_at"], days))  # noqa: E731
    traded = sum(1 for r in rows if r["trades"] > 0)
    returning = sum(1 for r in rows if r["sessions"] >= 2)

    daily: dict[str, set] = defaultdict(set)
    cutoff = now - timedelta(days=14)
    for uid, started in db.query(UserSession.user_id, UserSession.started_at).filter(UserSession.started_at >= cutoff).all():
        daily[_aware(started).strftime("%Y-%m-%d")].add(uid)
    signup_by_day: dict[str, int] = defaultdict(int)
    for r in rows:
        if within(r["created_at"], 14):
            signup_by_day[r["created_at"].strftime("%Y-%m-%d")] += 1
    return {
        "total_users": total, "signups_24h": signups(1), "signups_7d": signups(7), "signups_30d": signups(30),
        "active_24h": seen(1), "active_7d": seen(7), "active_30d": seen(30),
        "pct_ever_traded": round(100 * traded / total, 1) if total else 0.0,
        "pct_returning": round(100 * returning / total, 1) if total else 0.0,
        "pct_email_verified": round(100 * sum(1 for r in rows if r["email_verified"]) / total, 1) if total else 0.0,
        "total_trades": sum(r["trades"] for r in rows), "total_minutes_on_site": round(sum(r["minutes_on_site"] for r in rows), 1),
        "avg_minutes_per_user": round(sum(r["minutes_on_site"] for r in rows) / total, 1) if total else 0.0,
        "avg_sessions_per_user": round(sum(r["sessions"] for r in rows) / total, 2) if total else 0.0,
        "daily_active_last_14d": {d: len(s) for d, s in sorted(daily.items())},
        "signups_last_14d": dict(sorted(signup_by_day.items())),
    }
