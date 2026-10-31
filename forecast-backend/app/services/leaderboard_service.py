"""
Leaderboard: ranks REAL users only (never the House account, never the bot traders -- they are market participants,
not competitors, and the site says so) by net worth = wallet cash + what selling every held share would pay right now
(see portfolio_service) + treasury. One board, never resets: whoever has the most money wins. Recomputed on request
(memoised for a few seconds).
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.user import User
from app.services import portfolio_service

INCLUDE_BOTS = False  # bots trade to make the market, they do not compete on the leaderboard


def compute_leaderboard(db: Session, limit: int = 100) -> list[dict]:
    """The leaderboard by net worth, real users only."""
    worths = portfolio_service.compute_net_worths_cached(db, include_bots=INCLUDE_BOTS)
    users = {
        u.id: u for u in db.query(User).filter(User.id.in_(list(worths.keys()))).all()
    } if worths else {}
    rows: list[dict] = []
    for uid, w in worths.items():
        user = users.get(uid)
        if user is None:
            continue
        rows.append({
            "user_id": uid,
            "display_name": user.display_name,
            "tag": user.tag,
            "tag_color": user.tag_color,
            "cash_balance": w["cash"],
            "holdings_value": w["holdings"] + w["treasury"],
            "portfolio_value": w["net_worth"],
        })
    rows.sort(key=lambda r: (-r["portfolio_value"], r["display_name"].lower()))
    rows = rows[:limit]
    for i, row in enumerate(rows, start=1):
        row["rank"] = i
    return rows
