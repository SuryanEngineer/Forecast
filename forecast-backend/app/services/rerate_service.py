"""
Instant re-rate when a tournament's results are locked in.

A stock's fair price follows what it is expected to pay in dividends (bot_trading_service._fair_from_income). After a
big finish that number jumps, but listed prices only move a few percent per order, so for a while the stock would sit
well below fair and anyone who saw the result could buy it cheaply from the House. To close that window, finalizing a
tournament moves each participant's listed price most of the way to its new fair price at once:

    new price = old price x (fair / old price) ^ RERATE_WEIGHT        (a move of at most +/- RERATE_MAX_MOVE in log terms)

Bots and the order book take it the rest of the way. Written as a normal price point with volume 0 (no shares changed
hands). Failure here must never block finalizing, so the caller wraps it.
"""
from __future__ import annotations

import logging
import math
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.player import Player, PriceSnapshot
from app.models.tournament import Tournament
from app.services import book_price_service, bot_trading_service as bots, market_data_service

log = logging.getLogger(__name__)

RERATE_WEIGHT = 0.6          # fraction of the (log) gap to fair closed immediately
RERATE_MAX_MOVE = 0.60       # never more than about x1.8 / /1.8 in one go
RERATE_MIN_MOVE = 0.01       # ignore moves under 1%


def rerate_players(db: Session, player_ids: list[uuid.UUID]) -> int:
    """Re-rate these players now. Returns how many got a new price point. Caller commits."""
    ids = list(dict.fromkeys(player_ids))
    if not ids:
        return 0
    events, _local_first = bots._result_income(db, ids)
    first_seen = db.query(func.min(Tournament.start_time)).scalar()
    if first_seen is not None and first_seen.tzinfo is None:
        first_seen = first_seen.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    shares = {pid: max(1, n) for pid, n in db.query(Player.id, Player.total_shares_outstanding).filter(Player.id.in_(ids)).all()}
    last = market_data_service._bulk_latest_prices(db, ids)
    for pid, ipo in db.query(Player.id, Player.ipo_price).filter(Player.id.in_(ids)).all():
        last.setdefault(pid, ipo)
    listed = book_price_service.apply_book(db, last)

    written = 0
    for pid in ids:
        price = float(listed.get(pid, 0) or 0)
        if price <= 0 or pid not in shares:
            continue
        fair = float(bots._fair_from_income(bots.income_at(events.get(pid, []), now, first_seen) / shares[pid]))
        move = max(-RERATE_MAX_MOVE, min(RERATE_MAX_MOVE, RERATE_WEIGHT * math.log(fair / price)))
        if abs(math.exp(move) - 1.0) < RERATE_MIN_MOVE:
            continue
        new_price = max(0.01, price * math.exp(move))
        db.add(PriceSnapshot(id=uuid.uuid4(), player_id=pid, price=Decimal(str(round(new_price, 4))), volume=0))
        written += 1
    db.flush()
    return written
