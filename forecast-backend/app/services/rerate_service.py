"""
Instant re-rate when a tournament's results are locked in -- passing through the NEWS, not overwriting the market.

A result changes what a stock is expected to pay. Fair price before the result (with that tournament left out) vs after
(with it in) is exactly "the news"; the stock's REFERENCE price moves by that same ratio (damped by RERATE_WEIGHT):

    new reference = old reference x (fair after / fair before) ^ RERATE_WEIGHT        (at most +/- RERATE_MAX_MOVE in log terms)

So a player the market already over- or under-valued keeps that opinion -- only the new information is applied -- and the
band around fair value keeps the result sane. Written as a normal price point with volume 0 (no shares changed hands).
Failure here must never block finalizing, so the caller wraps it.
"""
from __future__ import annotations

import logging
import math
import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from app.engine import market_policy
from app.models.player import PriceSnapshot
from app.services import economic_params_service, fair_price_service, reference_service

log = logging.getLogger(__name__)

RERATE_WEIGHT = 0.8          # share of the fair-value change applied to the reference price
RERATE_MAX_MOVE = 0.70       # never more than about x2 / /2 in one go
RERATE_MIN_MOVE = 0.01       # ignore moves under 1%


def news_move(fair_before: float, fair_after: float, weight: float = RERATE_WEIGHT, max_move: float = RERATE_MAX_MOVE) -> float:
    """Multiplier to apply to the reference price for a fair-value change (1.0 = no change)."""
    if fair_before <= 0 or fair_after <= 0:
        return 1.0
    move = max(-max_move, min(max_move, weight * math.log(fair_after / fair_before)))
    return math.exp(move)


def rerate_players(db: Session, player_ids: list[uuid.UUID], tournament_ids: list[uuid.UUID] | None = None) -> int:
    """Re-rate these players now. `tournament_ids` are the results just locked in (needed to know what the news was; with
    none given nothing is changed). Returns how many got a new price point. Caller commits."""
    ids = list(dict.fromkeys(player_ids))
    if not ids or not tournament_ids:
        return 0
    before = fair_price_service.compute_fair(db, exclude_tournament_ids=tournament_ids)
    after = fair_price_service.compute_fair(db)
    fair_price_service.invalidate()
    low = economic_params_service.get_param(db, "market.band_low")
    high = economic_params_service.get_param(db, "market.band_high")
    refs = reference_service.get_refs(db, ids)

    written = 0
    for pid in ids:
        ref = refs.get(pid)
        if ref is None or pid not in after:
            continue
        # No fair price before = this is the stock's first result: the news is everything above the floor.
        factor = news_move(float(before.get(pid, Decimal("1.0"))), float(after[pid]))
        if abs(factor - 1.0) < RERATE_MIN_MOVE:
            continue
        new = market_policy.clamp_to_band(Decimal(ref) * Decimal(str(round(factor, 6))), after[pid], low, high)
        new = max(Decimal("0.01"), new).quantize(Decimal("0.0001"))
        reference_service.set_ref(db, pid, new)
        db.add(PriceSnapshot(id=uuid.uuid4(), player_id=pid, price=new, volume=0))
        written += 1
    db.flush()
    return written
