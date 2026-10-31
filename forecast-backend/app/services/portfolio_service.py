"""
Bulk net-worth computation shared by the leaderboards, daily snapshots, seasons and stats.

net worth = wallet cash (includes cash reserved for open buy orders) + shares x last traded price
            + treasury holdings (principal + accrued interest).
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.models.bot import BotProfile
from app.models.player import Player, Position, PriceSnapshot, ShareTransfer
from app.services import book_price_service, valuation_service
from app.models.treasury import TreasuryHolding, TreasuryHoldingStatus
from app.models.user import User
from app.models.wallet import Wallet
from app.services.house_account import HOUSE_ACCOUNT_EMAIL

ZERO = Decimal("0")
_CACHE: dict[str, tuple[float, dict]] = {}
CACHE_TTL_SECONDS = 10.0


def last_prices(db: Session) -> dict[uuid.UUID, Decimal]:
    """The LISTED price per player (midpoint of the best buy / sell price for one share, see market_policy.listed_price).
    Holdings are NOT valued at this price any more -- see compute_net_worths (liquidation value)."""
    return valuation_service.listed_prices(db)


def eligible_user_ids(db: Session, include_bots: bool = True) -> list[uuid.UUID]:
    # Smoke-test accounts (alice-123@test.local ...) are never real investors: out of every ranking and total.
    q = db.query(User.id).filter(User.email != HOUSE_ACCOUNT_EMAIL, User.is_active.is_(True), ~User.email.like("%@test.local"))
    if not include_bots:
        q = q.filter(User.id.notin_(select(BotProfile.user_id)))
    return [uid for (uid,) in q.all()]


def compute_net_worths(db: Session, user_ids: list[uuid.UUID] | None = None, include_bots: bool = True) -> dict[uuid.UUID, dict[str, Decimal]]:
    """{user_id: {cash, holdings, treasury, net_worth}} for the given users (default: every real+bot user)."""
    ids = set(user_ids) if user_ids is not None else set(eligible_user_ids(db, include_bots))
    if not ids:
        return {}
    # Holdings are worth what quick-selling the whole position would pay right now (real bids capped at the reference
    # price, then the House at its size-dependent price) -- not "shares x last trade", which one tiny trade could move.
    valuer = valuation_service.Valuer(db)
    out: dict[uuid.UUID, dict[str, Decimal]] = {uid: {"cash": ZERO, "holdings": ZERO, "treasury": ZERO} for uid in ids}

    for uid, cash in db.query(Wallet.user_id, Wallet.cash_balance).all():
        if uid in out:
            out[uid]["cash"] = cash
    for uid, pid, qty in db.query(Position.user_id, Position.player_id, Position.quantity).filter(Position.quantity > 0).all():
        if uid in out:
            out[uid]["holdings"] += valuer.value(pid, qty)
    for uid, principal, accrued in db.query(
        TreasuryHolding.user_id, TreasuryHolding.principal_amount, TreasuryHolding.accrued_interest
    ).filter(TreasuryHolding.status == TreasuryHoldingStatus.ACTIVE).all():
        if uid in out:
            out[uid]["treasury"] += principal + accrued
    for v in out.values():
        v["net_worth"] = v["cash"] + v["holdings"] + v["treasury"]
    return out


def compute_net_worths_cached(db: Session, include_bots: bool = True) -> dict[uuid.UUID, dict[str, Decimal]]:
    """Everyone's net worth, memoised for a few seconds -- leaderboard endpoints get hit by every open tab."""
    key = f"all:{include_bots}"
    hit = _CACHE.get(key)
    now = time.monotonic()
    if hit is not None and now - hit[0] < CACHE_TTL_SECONDS:
        return hit[1]
    data = compute_net_worths(db, None, include_bots)
    _CACHE[key] = (now, data)
    return data


def clear_cache() -> None:
    _CACHE.clear()


def day_change(db: Session, user_id: uuid.UUID, hours: int = 24) -> dict[str, Decimal]:
    """A user's real change in net worth over the last `hours`, as a number the dashboard can trust.

    change = net worth now - net worth `hours` ago - money the user added or took out (deposits / withdrawals).

    Net worth then is rebuilt exactly, not guessed from today's holdings:
      * cash then      = cash now - every signed cash movement since (trades, fees, dividends, treasury moves, deposits);
      * shares then    = shares now - every share-ledger delta since, valued at the price in force back then;
      * treasury then  = treasury now, undone for treasury purchases / redemptions made since.
    So buying a stock today does not look like a gain or a loss (cash became shares at the same value), a dividend does
    count as a gain, and a brand-new account starts from zero change. The percentage is relative to what the user had
    at the start of the window (plus anything deposited during it)."""
    from app.models.wallet import LedgerEntry, LedgerEntryType
    from app.services import market_data_service

    now = datetime.now(timezone.utc)
    t0 = now - timedelta(hours=hours)
    nw_now = compute_net_worths(db, [user_id]).get(user_id, {"cash": ZERO, "holdings": ZERO, "treasury": ZERO, "net_worth": ZERO})

    wallet = db.query(Wallet).filter(Wallet.user_id == user_id).one_or_none()
    cash_delta = flow = treasury_moved = ZERO
    if wallet is not None:
        for etype, total in (
            db.query(LedgerEntry.entry_type, func.coalesce(func.sum(LedgerEntry.amount), 0))
            .filter(LedgerEntry.wallet_id == wallet.id, LedgerEntry.created_at > t0)
            .group_by(LedgerEntry.entry_type)
            .all()
        ):
            total = Decimal(str(total or 0))
            cash_delta += total
            if etype in (LedgerEntryType.DEPOSIT, LedgerEntryType.WITHDRAWAL):
                flow += total
            elif etype == LedgerEntryType.TREASURY_BUY:
                treasury_moved += -total          # cash out of the wallet, into treasury
            elif etype == LedgerEntryType.TREASURY_REDEEM:
                treasury_moved -= total           # cash back into the wallet, out of treasury
    cash_then = nw_now["cash"] - cash_delta
    treasury_then = max(ZERO, nw_now["treasury"] - treasury_moved)

    now_qty = {pid: qty for pid, qty in db.query(Position.player_id, Position.quantity).filter(Position.user_id == user_id, Position.quantity > 0).all()}
    moved = {pid: int(d or 0) for pid, d in db.query(ShareTransfer.player_id, func.sum(ShareTransfer.delta)).filter(ShareTransfer.user_id == user_id, ShareTransfer.occurred_at > t0).group_by(ShareTransfer.player_id).all()}
    pids = set(now_qty) | set(moved)
    valuer = valuation_service.Valuer(db, list(pids)) if pids else None
    price_then = market_data_service._bulk_latest_prices(db, list(pids), before=t0) if pids else {}
    holdings_then = ZERO
    for pid in pids:
        qty_then = now_qty.get(pid, 0) - moved.get(pid, 0)
        if qty_then > 0:
            # Same yardstick at both ends: the price then, with today's size haircut (what a position this big fetches
            # relative to the headline price), so buying or selling shares is value-neutral and only real moves count.
            px_then = price_then.get(pid, valuer.listed(pid))
            holdings_then += qty_then * px_then * valuer.haircut(pid, now_qty.get(pid, qty_then))

    nw_then = cash_then + holdings_then + treasury_then
    change = nw_now["net_worth"] - nw_then - flow
    base = nw_then + max(ZERO, flow)
    pct = (change / base * 100) if base > 0 else ZERO
    return {"net_worth": nw_now["net_worth"], "net_worth_then": nw_then, "change": change, "change_pct": pct, "hours": Decimal(hours)}
