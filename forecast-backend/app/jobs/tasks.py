"""
Background job functions. Each one opens its own DB session (RQ runs
these in a separate worker process, so they can't reuse a request's
session) and is responsible for its own commit/rollback -- which is also
exactly what makes them safe to call directly/synchronously whenever
Redis is disabled (see the `enqueue_*` wrappers at the bottom of this
file, gated on settings.REDIS_ENABLED rather than DEMO_MODE -- see
app/core/config.py): there's no RQ-specific behavior (retries, a
separate worker process, etc.) that those callers actually depend on
today.
"""
from __future__ import annotations

import uuid

from app.core.config import settings
from app.db.session import SessionLocal


def process_dividend_payout_job(payout_id: str) -> None:
    from app.services import dividend_service  # local import avoids a circular import at module load time

    db = SessionLocal()
    try:
        dividend_service.process_payout(db, uuid.UUID(payout_id))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def accrue_treasury_job() -> None:
    """Intended to run once per day (see README_SETUP.md for a cron / RQ
    scheduler example) -- accrues one day of interest onto every ACTIVE
    TreasuryHolding."""
    from app.services import treasury_service

    db = SessionLocal()
    try:
        treasury_service.accrue_all_active_holdings(db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def refresh_bot_quotes_job(player_id: str) -> None:
    """Optional: re-post the House's liquidity ladder around the latest
    price for one player. Not scheduled automatically in v1 -- call it
    manually or wire it to a schedule once the simulation decides how
    often liquidity should refresh."""
    from app.models.player import Player
    from app.services import market_maker_service

    db = SessionLocal()
    try:
        player = db.get(Player, uuid.UUID(player_id))
        if player is not None:
            market_maker_service.post_bot_quotes(db, player)
            db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def enqueue_dividend_payout(payout_id: str) -> None:
    if not settings.REDIS_ENABLED:
        # No Redis/RQ worker -- run it synchronously, in-process, right
        # now instead of queuing it. See module docstring for why that's
        # safe.
        process_dividend_payout_job(payout_id)
        return
    from app.jobs.queue import default_queue

    default_queue.enqueue(process_dividend_payout_job, payout_id)


def enqueue_treasury_accrual() -> None:
    if not settings.REDIS_ENABLED:
        accrue_treasury_job()
        return
    from app.jobs.queue import default_queue

    default_queue.enqueue(accrue_treasury_job)


def enqueue_bot_quote_refresh(player_id: str) -> None:
    if not settings.REDIS_ENABLED:
        refresh_bot_quotes_job(player_id)
        return
    from app.jobs.queue import default_queue

    default_queue.enqueue(refresh_bot_quotes_job, player_id)
