"""
Keeps the database small as the bots trade. The Supabase free plan has a 500 MB disk; every trade writes a Trade row,
a PriceSnapshot, two share-ledger rows and several wallet-ledger rows (~1.7 KB), so a lively bot market would fill it
in weeks. Everything pruned here is BOT-ONLY history that nothing user-facing needs after a few days:

  * bot-vs-bot trades older than RETENTION_BOT_TRADE_DAYS (the live-activity feed only shows recent ones);
  * bot / House trade-related wallet ledger rows (trade debit/credit, order hold/release, fees) older than the same;
  * finished (filled / cancelled / rejected) orders of bots older than the same;
  * bot share-transfer ledger rows older than RETENTION_SHARE_LEDGER_DAYS (holdings_at() only ever reads rows AFTER a
    tournament's start time, so rows older than any pending payout window are dead weight);
  * price_snapshots older than RETENTION_SNAPSHOT_DAYS thinned to one per player per hour (charts stay smooth; the
    newest snapshot of every player is always kept because it is the latest hour's survivor).

Never touched: anything a human did (trades, ledger, orders, share transfers), dividend / treasury / deposit ledger rows,
open orders, and positions / balances (those are stored directly, not derived from the pruned rows). Each statement is
chunked so a big backlog is worked off a bit per pass instead of one long lock. Idempotent and fault-isolated.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.bot import BotProfile
from app.models.order import Order, OrderStatus, Trade
from app.models.player import PriceSnapshot, ShareTransfer
from app.models.user import User
from app.models.wallet import LedgerEntry, LedgerEntryType, Wallet
from app.services.house_account import HOUSE_ACCOUNT_EMAIL

logger = logging.getLogger("forecast.retention")

CHUNK = 5000
MAX_CHUNKS_PER_TABLE = 6  # per pass; a backlog is cleared over several passes
RUN_EVERY_SECONDS = 20 * 60
_last_run = 0.0

_TRADE_LEDGER_TYPES = [
    LedgerEntryType.TRADE_DEBIT,
    LedgerEntryType.TRADE_CREDIT,
    LedgerEntryType.ORDER_HOLD,
    LedgerEntryType.ORDER_RELEASE,
    LedgerEntryType.FEE,
]


def _delete_chunked(db: Session, model, where) -> int:
    total = 0
    for _ in range(MAX_CHUNKS_PER_TABLE):
        ids = [i for (i,) in db.query(model.id).filter(where).limit(CHUNK).all()]
        if not ids:
            break
        db.query(model).filter(model.id.in_(ids)).delete(synchronize_session=False)
        db.commit()
        total += len(ids)
        if len(ids) < CHUNK:
            break
    return total


def _bot_user_ids(db: Session) -> list:
    ids = [uid for (uid,) in db.query(BotProfile.user_id).all()]
    house = db.query(User.id).filter(User.email == HOUSE_ACCOUNT_EMAIL).scalar()
    if house is not None:
        ids.append(house)
    return ids


def _thin_snapshots(db: Session, cutoff: datetime) -> int:
    """Postgres only (uses date_trunc / window functions); a no-op on SQLite demo databases."""
    if db.bind is None or db.bind.dialect.name != "postgresql":
        return 0
    removed = 0
    for _ in range(MAX_CHUNKS_PER_TABLE):
        res = db.execute(
            text(
                """
                DELETE FROM price_snapshots WHERE id IN (
                  SELECT id FROM (
                    SELECT id, row_number() OVER (
                             PARTITION BY player_id, date_trunc('hour', recorded_at)
                             ORDER BY recorded_at DESC) AS rn
                    FROM price_snapshots WHERE recorded_at < :cutoff
                  ) ranked WHERE rn > 1 LIMIT :chunk
                )
                """
            ),
            {"cutoff": cutoff, "chunk": CHUNK},
        )
        db.commit()
        n = res.rowcount or 0
        removed += n
        if n < CHUNK:
            break
    return removed


def run_retention(db: Session, force: bool = False) -> dict:
    global _last_run
    if not getattr(settings, "RETENTION_ENABLED", True):
        return {"skipped": "disabled"}
    now_m = time.monotonic()
    if not force and _last_run and now_m - _last_run < RUN_EVERY_SECONDS:
        return {"skipped": "recent"}
    _last_run = now_m

    now = datetime.now(timezone.utc)
    trade_cut = now - timedelta(days=max(1, int(settings.RETENTION_BOT_TRADE_DAYS)))
    share_cut = now - timedelta(days=max(7, int(settings.RETENTION_SHARE_LEDGER_DAYS)))
    snap_cut = now - timedelta(days=max(2, int(settings.RETENTION_SNAPSHOT_DAYS)))
    out: dict = {}
    bots = _bot_user_ids(db)

    steps = [
        ("bot_trades", lambda: _delete_chunked(db, Trade, and_(Trade.buyer_is_bot.is_(True), Trade.seller_is_bot.is_(True), Trade.executed_at < trade_cut))),
    ]
    if bots:
        bot_wallets = db.query(Wallet.id).filter(Wallet.user_id.in_(bots)).subquery()
        steps += [
            (
                "bot_ledger",
                lambda: _delete_chunked(
                    db,
                    LedgerEntry,
                    and_(LedgerEntry.wallet_id.in_(db.query(bot_wallets.c.id)), LedgerEntry.entry_type.in_(_TRADE_LEDGER_TYPES), LedgerEntry.created_at < trade_cut),
                ),
            ),
            (
                "bot_orders",
                lambda: _delete_chunked(
                    db,
                    Order,
                    and_(
                        Order.user_id.in_(bots),
                        Order.status.in_([OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED]),
                        Order.created_at < trade_cut,
                    ),
                ),
            ),
            ("bot_share_ledger", lambda: _delete_chunked(db, ShareTransfer, and_(ShareTransfer.user_id.in_(bots), ShareTransfer.occurred_at < share_cut))),
        ]
    steps.append(("snapshots_thinned", lambda: _thin_snapshots(db, snap_cut)))

    for name, fn in steps:
        try:
            out[name] = fn()
        except Exception:
            db.rollback()
            logger.exception("Retention step %s failed -- will retry next pass", name)
    if any(v for v in out.values() if isinstance(v, int)):
        logger.info("Retention: %s", out)
    return out
