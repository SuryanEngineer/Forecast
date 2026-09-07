"""
Leaderboard: ranks real users (never the House account, never a bot
trader -- see app/services/bot_trading_service.py) by total portfolio
value = wallet cash + held shares valued at each player's current
last-traded price (see app/services/market_data_service.py for what
"last price" means). Recomputed on every request rather than
cached/materialized -- fine at prototype scale (roadmap's "correct and
testable, not yet production-hardened" phase); a materialized snapshot
refreshed on a schedule would be the follow-up once the user count makes
recomputing this on every page load too slow.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.bot import BotProfile
from app.models.player import Player, PriceSnapshot, Position
from app.models.user import User
from app.services.house_account import HOUSE_ACCOUNT_EMAIL


def _last_price_by_player(db: Session) -> dict[uuid.UUID, Decimal]:
    """One query for every player's most recent PriceSnapshot, instead of
    one query per player -- this is what keeps the leaderboard from being
    O(players) database round-trips on top of O(users)."""
    prices: dict[uuid.UUID, Decimal] = {}
    # SQLAlchemy-portable "latest row per group": pull everything ordered
    # oldest-first per player and let the dict overwrite keep only the
    # last one seen. Fine at prototype scale; a window function
    # (ROW_NUMBER() OVER (PARTITION BY player_id ORDER BY recorded_at DESC))
    # would be the Postgres-native way to do this in one indexed pass once
    # price_snapshots grows large.
    snapshots = db.query(PriceSnapshot).order_by(PriceSnapshot.recorded_at.asc()).all()
    for snap in snapshots:
        prices[snap.player_id] = snap.price
    ipo_fallback = {p.id: p.ipo_price for p in db.query(Player).all()}
    for player_id, ipo_price in ipo_fallback.items():
        prices.setdefault(player_id, ipo_price)
    return prices


def compute_leaderboard(db: Session, limit: int = 100) -> list[dict]:
    prices = _last_price_by_player(db)

    bot_user_ids = db.query(BotProfile.user_id).subquery()
    users = (
        db.query(User)
        .filter(User.email != HOUSE_ACCOUNT_EMAIL, User.is_active.is_(True), User.id.notin_(bot_user_ids))
        .all()
    )
    rows: list[dict] = []
    for user in users:
        wallet = user.wallet
        cash = wallet.cash_balance if wallet is not None else Decimal("0")
        holdings_value = Decimal("0")
        positions = db.query(Position).filter(Position.user_id == user.id, Position.quantity > 0).all()
        for position in positions:
            price = prices.get(position.player_id, Decimal("0"))
            holdings_value += price * position.quantity
        rows.append({
            "user_id": user.id,
            "display_name": user.display_name,
            "cash_balance": cash,
            "holdings_value": holdings_value,
            "portfolio_value": cash + holdings_value,
        })

    rows.sort(key=lambda r: r["portfolio_value"], reverse=True)
    for i, row in enumerate(rows[:limit], start=1):
        row["rank"] = i
    return rows[:limit]
