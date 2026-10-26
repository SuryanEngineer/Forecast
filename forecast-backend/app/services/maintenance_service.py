"""
Self-contained housekeeping that needs no cron / Redis worker / second process. Run every minute by the background
loop in app/main.py. Every step is idempotent and individually fault-isolated:

 1. dividends   - pays any dividend payout still PENDING/PROCESSING (e.g. a finalize that happened while the
                  worker was down, or a crash mid-way). Each payout commits on its own.
 2. treasury    - accrues whole days of interest on active treasury holdings (previously nothing scheduled this).
 3. snapshots   - upserts today's net-worth snapshot for every user (feeds best/worst day) every ~15 min.
 4. seasons     - finalizes an ended season / activates a scheduled one.
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.dividend import DividendPayout, DividendPayoutStatus
from app.services import dividend_service, season_service, stats_service, treasury_service

logger = logging.getLogger("forecast.maintenance")
SNAPSHOT_EVERY_SECONDS = 15 * 60
_last_snapshot = 0.0


def sweep_pending_payouts(db: Session, limit: int = 200) -> int:
    q = db.query(DividendPayout.id).filter(
        DividendPayout.status.in_([DividendPayoutStatus.PENDING, DividendPayoutStatus.PROCESSING])
    )
    if settings.REDIS_ENABLED:
        # A real RQ worker may be about to pick fresh ones up -- only take over the ones it has had 5 minutes for.
        q = q.filter(DividendPayout.created_at < datetime.now(timezone.utc) - timedelta(minutes=5))
    ids = [pid for (pid,) in q.order_by(DividendPayout.created_at.asc()).limit(limit).all()]
    done = 0
    for pid in ids:
        try:
            dividend_service.process_payout(db, uuid.UUID(str(pid)))
            db.commit()
            done += 1
        except Exception:
            db.rollback()
            logger.exception("Dividend payout %s failed -- will retry next pass", pid)
    return done


def run_maintenance_pass(db: Session, force_snapshot: bool = False) -> dict:
    global _last_snapshot
    out: dict = {}
    for name, fn in (
        ("payouts_processed", lambda: sweep_pending_payouts(db)),
        ("treasury_accrued", lambda: treasury_service.accrue_due_holdings(db)),
        ("season_actions", lambda: season_service.run_rollover(db)),
    ):
        try:
            out[name] = fn()
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Maintenance step %s failed", name)
    now = time.monotonic()
    if force_snapshot or now - _last_snapshot >= SNAPSHOT_EVERY_SECONDS:
        try:
            out["snapshots"] = stats_service.snapshot_all(db)
            db.commit()
            _last_snapshot = now
        except Exception:
            db.rollback()
            logger.exception("Snapshot step failed")
    return out
