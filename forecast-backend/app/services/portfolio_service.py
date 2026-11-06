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


def _thin_series(pts: list[tuple[datetime, float]], limit: int) -> list[tuple[datetime, float]]:
    """Cut a long series to roughly `limit`..`2*limit` points WITHOUT smoothing it: time is split into `limit` equal buckets and
    each bucket keeps its first, lowest, highest and last point (in time order), so every peak and dip survives."""
    if len(pts) <= limit * 2:
        return pts
    t_first, t_last = pts[0][0], pts[-1][0]
    span = max((t_last - t_first).total_seconds(), 1e-9)
    buckets: dict[int, list[tuple[datetime, float]]] = {}
    for p in pts:
        b = min(limit - 1, int((p[0] - t_first).total_seconds() / span * limit))
        buckets.setdefault(b, []).append(p)
    out: list[tuple[datetime, float]] = []
    for b in sorted(buckets):
        rows = buckets[b]
        keep = {id(rows[0]): rows[0], id(rows[-1]): rows[-1]}
        lo = min(rows, key=lambda r: r[1])
        hi = max(rows, key=lambda r: r[1])
        keep[id(lo)] = lo
        keep[id(hi)] = hi
        out.extend(sorted(keep.values(), key=lambda r: r[0]))
    return out


# Ledger rows and share-ledger rows written by ONE trade carry timestamps a few milliseconds apart; treating them as separate
# moments would draw a fake dip (cash gone, shares not yet arrived). Anything inside this window counts as the same moment.
_SAME_MOMENT = timedelta(seconds=2)


def net_worth_series(db: Session, user_id: uuid.UUID, hours: int = 24, points: int = 300) -> list[dict]:
    """The user's net worth over time as a true step-by-step curve, not a handful of samples.

    Net worth at any instant = cash + shares owned x each stock's price + treasury. So the curve changes whenever
      * the user's cash changes (a trade, fee, dividend, deposit, treasury move)      -> cash ledger,
      * the user's share counts change (they bought or sold)                          -> share ledger,
      * a stock they hold trades at a new price                                       -> price snapshots,
    and the value in between is flat. We rebuild exactly that:
      1. the state at the start of the window = the state now, with every later movement undone;
      2. one forward pass over all those events in time order, keeping cash / treasury / per-stock quantity and price, and
         the holdings total updated incrementally (O(events), no per-point rescans);
      3. a point after each event (price moves of stocks the user does not hold are skipped, they change nothing).
    Same yardstick as day_change (size haircut at today's position size), so the chart's end-to-end change agrees with the
    "past 24h" number. `hours`=0 means since the account began. The last point is the live net worth.
    Long series are thinned by min/max bucketing (see _thin_series), so the jaggedness is kept. Returns oldest first."""
    from app.models.wallet import LedgerEntry, LedgerEntryType
    from app.services import market_data_service

    hours = max(0, min(int(hours), 24 * 400))
    points = max(2, min(int(points), 600))
    now = datetime.now(timezone.utc)
    nw_now = compute_net_worths(db, [user_id]).get(user_id)
    if nw_now is None:
        return []
    wallet = db.query(Wallet).filter(Wallet.user_id == user_id).one_or_none()

    def aware(dt: datetime) -> datetime:
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    first_seen = now
    if wallet is not None:
        first = db.query(func.min(LedgerEntry.created_at)).filter(LedgerEntry.wallet_id == wallet.id).scalar()
        if first is not None:
            first_seen = aware(first)
    first_move = db.query(func.min(ShareTransfer.occurred_at)).filter(ShareTransfer.user_id == user_id).scalar()
    if first_move is not None:
        first_seen = min(first_seen, aware(first_move))
    t0 = first_seen - timedelta(seconds=1) if hours == 0 else now - timedelta(hours=hours)
    t0 = max(t0, first_seen - timedelta(seconds=1))
    live = float(nw_now["net_worth"])

    # Cash-moving ledger rows in the window (zero-amount order hold / release rows change nothing, so they are not loaded).
    led: list[tuple[datetime, "LedgerEntryType", Decimal]] = []
    if wallet is not None:
        led = [
            (aware(c), et, Decimal(str(a or 0)))
            for c, et, a in db.query(LedgerEntry.created_at, LedgerEntry.entry_type, LedgerEntry.amount)
            .filter(LedgerEntry.wallet_id == wallet.id, LedgerEntry.created_at > t0, LedgerEntry.amount != 0)
            .order_by(LedgerEntry.created_at.asc())
            .all()
        ]
    now_qty = {pid: int(q) for pid, q in db.query(Position.player_id, Position.quantity).filter(Position.user_id == user_id, Position.quantity > 0).all()}
    moves = [
        (aware(at), pid, int(d))
        for pid, d, at in db.query(ShareTransfer.player_id, ShareTransfer.delta, ShareTransfer.occurred_at)
        .filter(ShareTransfer.user_id == user_id, ShareTransfer.occurred_at > t0)
        .order_by(ShareTransfer.occurred_at.asc())
        .all()
    ]
    pids = list(set(now_qty) | {pid for _t, pid, _d in moves})

    # State at t0: today's state with everything after t0 undone.
    cash = nw_now["cash"] - sum((a for _c, _et, a in led), ZERO)
    treasury = nw_now["treasury"]
    for _c, et, a in led:
        if et == LedgerEntryType.TREASURY_BUY:
            treasury -= -a        # undo: that cash went INTO treasury
        elif et == LedgerEntryType.TREASURY_REDEEM:
            treasury += a         # undo: that cash came OUT of treasury
    treasury = max(ZERO, treasury)
    qty: dict[uuid.UUID, int] = dict(now_qty)
    for _c, pid, d in moves:
        qty[pid] = qty.get(pid, 0) - d

    one = Decimal("1")
    valuer = valuation_service.Valuer(db, pids) if pids else None
    haircut = {pid: valuer.haircut(pid, now_qty.get(pid, 1)) for pid in pids} if valuer else {}
    price: dict[uuid.UUID, Decimal] = {}
    if pids:
        price = dict(market_data_service._bulk_latest_prices(db, pids, before=t0))
        for pid in pids:
            if not price.get(pid):
                price[pid] = valuer.listed(pid)

    # One event stream, in time order. kind: 0 cash, 1 shares, 2 price.
    events: list[tuple[datetime, int, object, object]] = []
    events.extend((c, 0, et, a) for c, et, a in led)
    events.extend((c, 1, pid, d) for c, pid, d in moves)
    if pids:
        for pid, px, at in (
            db.query(PriceSnapshot.player_id, PriceSnapshot.price, PriceSnapshot.recorded_at)
            .filter(PriceSnapshot.player_id.in_(pids), PriceSnapshot.recorded_at > t0)
            .order_by(PriceSnapshot.recorded_at.asc())
            .all()
        ):
            events.append((aware(at), 2, pid, px))
    events.sort(key=lambda e: e[0])

    def contribution(pid: uuid.UUID) -> Decimal:
        q = qty.get(pid, 0)
        return q * price.get(pid, ZERO) * haircut.get(pid, one) if q > 0 else ZERO

    holdings = sum((contribution(pid) for pid in pids), ZERO)
    pts: list[tuple[datetime, float]] = []
    if t0 >= first_seen:
        pts.append((t0, float(cash + holdings + treasury)))

    n = len(events)
    for i, (t, kind, a, b) in enumerate(events):
        emit = True
        if kind == 0:
            cash += b
            if a == LedgerEntryType.TREASURY_BUY:
                treasury += -b
            elif a == LedgerEntryType.TREASURY_REDEEM:
                treasury = max(ZERO, treasury - b)
        elif kind == 1:
            before = contribution(a)
            qty[a] = qty.get(a, 0) + b
            holdings += contribution(a) - before
        else:
            q = qty.get(a, 0)
            if q > 0:
                before = contribution(a)
                price[a] = b
                holdings += contribution(a) - before
            else:
                price[a] = b
                emit = False          # a stock the user does not hold at that moment: no effect on their curve
        if kind != 2 and i + 1 < n and events[i + 1][1] != 2 and events[i + 1][0] - t < _SAME_MOMENT:
            emit = False              # still inside the same trade: wait for its other half
        if emit and t >= first_seen:
            pts.append((t, float(cash + holdings + treasury)))

    # Each point is held until the next event, so draw a flat run into every change: that makes the line a true step curve
    # rather than slanting between distant events.
    stepped: list[tuple[datetime, float]] = []
    for t, v in pts:
        if stepped and t > stepped[-1][0] and stepped[-1][1] != v:
            stepped.append((t - timedelta(milliseconds=1), stepped[-1][1]))
        stepped.append((t, v))
    stepped.append((now, live))
    stepped = _thin_series(stepped, points)
    return [{"t": t.isoformat(), "net_worth": v} for t, v in stepped]


def dividend_markers(db: Session, user_id: uuid.UUID, hours: int = 24) -> list[dict]:
    """The tournaments that paid this user a dividend inside the chart window, one entry per tournament, so the portfolio chart
    can mark the jumps they caused. `amount` is everything that tournament paid the user (summed over the players they held),
    `t` is when the money landed. `hours`=0 means since the account began. Oldest first."""
    from app.models.dividend import DividendLineItem, DividendPayout
    from app.models.tournament import Tournament
    from app.models.wallet import LedgerEntry

    hours = max(0, min(int(hours), 24 * 400))
    t0 = None if hours == 0 else datetime.now(timezone.utc) - timedelta(hours=hours)
    paid_at = func.coalesce(LedgerEntry.created_at, DividendLineItem.created_at)
    q = (
        db.query(Tournament.id, Tournament.name, DividendLineItem.amount_paid, paid_at, Player.gamertag)
        .select_from(DividendLineItem)
        .join(DividendPayout, DividendPayout.id == DividendLineItem.payout_id)
        .join(Tournament, Tournament.id == DividendPayout.tournament_id)
        .join(Player, Player.id == DividendPayout.player_id)
        .outerjoin(LedgerEntry, LedgerEntry.id == DividendLineItem.ledger_entry_id)
        .filter(DividendLineItem.user_id == user_id, DividendLineItem.amount_paid > 0)
    )
    if t0 is not None:
        q = q.filter(paid_at > t0)
    groups: dict[uuid.UUID, dict] = {}
    for tid, name, amount, at, tag in q.all():
        at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
        g = groups.setdefault(tid, {"tournament_id": str(tid), "name": name, "amount": ZERO, "t": at, "players": []})
        g["amount"] += Decimal(str(amount or 0))
        g["t"] = max(g["t"], at)
        if tag and tag not in g["players"]:
            g["players"].append(tag)
    out = sorted(groups.values(), key=lambda g: g["t"])
    return [{**g, "amount": float(g["amount"]), "t": g["t"].isoformat(), "players": g["players"][:4]} for g in out]
