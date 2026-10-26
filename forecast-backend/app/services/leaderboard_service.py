"""
Leaderboard: ranks users (never the House account; bot traders -- see
app/services/bot_trading_service.py -- are included while INCLUDE_BOTS is on, so the
market looks populated at launch) by total portfolio
value = wallet cash + held shares valued at each player's current
last-traded price (see app/services/market_data_service.py for what
"last price" means). Recomputed on every request rather than
cached/materialized -- fine at prototype scale (roadmap's "correct and
testable, not yet production-hardened" phase); a materialized snapshot
refreshed on a schedule would be the follow-up once the user count makes
recomputing this on every page load too slow.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.user import User
from app.services import portfolio_service

# Flip to False to rank only real users once the real player base is big enough.
INCLUDE_BOTS = True


def compute_leaderboard(db: Session, limit: int = 100) -> list[dict]:
    """All-time (never resets) leaderboard by total net worth = cash + shares at last price + treasury."""
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
