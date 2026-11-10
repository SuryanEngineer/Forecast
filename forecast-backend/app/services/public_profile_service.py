"""
What anyone may see about another investor (the popup you get by clicking a name on the leaderboard).

Deliberately LIMITED: who they are, where they rank, their cash, the shares they hold (with what each position is worth), their
net worth over time, and their lifetime dividends and fees. NOT shown: orders, trade history, activity, cost basis / profit per
holding, email or anything about the account itself. Only people who are on the leaderboard (real, active, non-bot users) can
be looked up; anyone else is "not found".
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.player import Player, Position
from app.services import leaderboard_service, portfolio_service, stats_service, valuation_service

ZERO = Decimal("0")
MAX_HOLDINGS = 300
CHART_POINTS = 150


def _f(x: Decimal | None) -> float:
    return float(x or ZERO)


def public_profile(db: Session, user_id: uuid.UUID, hours: int = 0) -> dict | None:
    """The public profile of one leaderboard investor, or None if they are not on the leaderboard."""
    board = leaderboard_service.compute_leaderboard(db, limit=1_000_000)
    row = next((r for r in board if r["user_id"] == user_id), None)
    if row is None:
        return None

    worth = portfolio_service.compute_net_worths_cached(db, include_bots=False).get(user_id)
    cash = worth["cash"] if worth else row["cash_balance"]
    shares_value = worth["holdings"] if worth else ZERO
    treasury_value = worth["treasury"] if worth else ZERO

    positions = (
        db.query(Position, Player)
        .join(Player, Player.id == Position.player_id)
        .filter(Position.user_id == user_id, Position.quantity > 0)
        .all()
    )
    holdings: list[dict] = []
    if positions:
        valuer = valuation_service.Valuer(db, [p.player_id for p, _pl in positions])
        for pos, player in positions:
            holdings.append({
                "player_id": player.id, "gamertag": player.gamertag, "is_verified": bool(player.is_verified),
                "shares": int(pos.quantity), "price": _f(valuer.listed(player.id)), "value": _f(valuer.value(player.id, pos.quantity)),
            })
        holdings.sort(key=lambda h: (-h["value"], h["gamertag"].lower()))

    totals = stats_service.ledger_totals(db, user_id)
    series = portfolio_service.net_worth_series(db, user_id, hours, CHART_POINTS)

    return {
        "user_id": user_id,
        "display_name": row["display_name"], "tag": row["tag"], "tag_color": row["tag_color"],
        "rank": row["rank"], "investors": len(board),
        "net_worth": _f(row["portfolio_value"]), "cash": _f(cash),
        "shares_value": _f(shares_value), "treasury_value": _f(treasury_value),
        "dividend_earnings": _f(totals["dividends"]), "dividend_payouts": totals["dividend_payouts"],
        "fees_paid": _f(totals["fees"]),
        "holdings_count": len(holdings), "holdings": holdings[:MAX_HOLDINGS],
        "points": series,
    }
