"""
The dividend-based FAIR price of every active stock, in one place (order band, bots, re-rating, reports all read this).

    fair = projected yearly dividends per share / TARGET_YIELD         (see bot_trading_service._fair_from_income)

With the market anchor on (platform parameter market.anchor_value > 0) TARGET_YIELD is solved so that all fair prices add up to
the anchor: a stock is worth its SHARE of all expected dividends, so the size of the pools never moves the price level.

Projected income is the last 12 months of results, but ONE huge result must not price a stock for a whole year. So the
stock's own income is SHRUNK toward the roster's typical income, more strongly the fewer results it is based on:

    income = w x own + (1 - w) x roster median,     w = n / (n + SHRINK_K)     (n = results in the window; n = 0 -> no income)

A player with 1 result (maybe a fluke) is mostly priced like a typical player; with 6 results the stock's own record
counts for half, with 20 for ~77%. Real stars have many results, so they are barely affected.

Cached in-process (it reads every result): FAIR_CACHE_SECONDS; `invalidate()` after a tournament lands.
"""
from __future__ import annotations

import statistics
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.player import Player
from app.services import bot_trading_service as bots, economic_params_service

SHRINK_K = 6.0
FAIR_CACHE_SECONDS = 600
_CACHE: dict = {"t": 0.0, "fair": {}}


def shrunk_income(own: float, n: int, prior: float, k: float = SHRINK_K) -> float:
    """Blend a stock's own projected income toward the roster prior by how much evidence (n results) backs it."""
    if n <= 0:
        return 0.0
    w = n / (n + k)
    return w * own + (1.0 - w) * prior


def anchor_value(db: Session) -> float:
    """Total fair market value in dollars (platform parameter market.anchor_value); 0 = off (fixed target yield)."""
    try:
        v = float(economic_params_service.get_param(db, "market.anchor_value"))
    except Exception:  # noqa: BLE001 -- never let a missing/odd parameter break pricing
        return 0.0
    return v if v > 0 else 0.0


def effective_yield(db: Session, inc: dict, shares: dict, live: bool = True) -> float:
    """The yield fair prices are computed with.

    Anchor off: the stored market.target_yield (fair price level follows the dividend pools).
    Anchor on: the yield that makes every stock's fair price add up to the anchor, solved from today's projected incomes. A
    stock's fair price is then its SHARE of all expected dividends times the anchor, so multiplying every pool by k multiplies
    every income and the yield by k and leaves every price exactly where it was; only RELATIVE dividends move prices.
    `live` also stores it as the in-process yield the rest of the pricing code reads."""
    anchor = anchor_value(db)
    if anchor <= 0:
        return refresh_target_yield(db)
    pids = list(inc)
    if not pids:
        return bots.TARGET_YIELD
    from app.engine import market_policy

    y = market_policy.solve_target_yield([inc[p] for p in pids], [shares[p] for p in pids], anchor, bots.FAIR_MIN, bots.FAIR_MAX)
    if live and y > 0:
        bots.TARGET_YIELD = y
    return y if y > 0 else bots.TARGET_YIELD


def refresh_target_yield(db: Session) -> float:
    """Loads the stored target yield (platform parameter market.target_yield) into the live pricing formula. Called before
    any fair price is computed, so changing the parameter (scripts/simulate_price_history.py --market-multiple) is all it takes.
    With the market anchor on the yield is solved from the incomes instead (effective_yield), so this leaves it alone."""
    if anchor_value(db) > 0:
        return bots.TARGET_YIELD
    try:
        y = float(economic_params_service.get_param(db, "market.target_yield"))
    except Exception:  # noqa: BLE001 -- never let a missing/odd parameter break pricing
        return bots.TARGET_YIELD
    if y > 0:
        bots.TARGET_YIELD = y
    return bots.TARGET_YIELD


def income_per_share(db: Session, exclude_tournament_ids: list[uuid.UUID] | None = None, at: datetime | None = None) -> tuple[dict[uuid.UUID, float], dict[uuid.UUID, int]]:
    """({player: fluke-shrunk projected yearly dividends per share}, {player: shares}) for every ACTIVE player that has a
    results history. Fair price is this divided by the target yield."""
    players = db.query(Player.id, Player.total_shares_outstanding).filter(Player.is_active.is_(True)).all()
    ids = [pid for pid, _ in players]
    shares = {pid: max(1, n) for pid, n in players}
    events, first_seen = bots._result_income(db, ids, exclude_tournament_ids)
    now = at or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=bots.INCOME_WINDOW_DAYS)

    own: dict[uuid.UUID, float] = {}
    count: dict[uuid.UUID, int] = {}
    for pid in ids:
        ev = events.get(pid, [])
        count[pid] = sum(1 for (t, _v) in ev if cutoff < t <= now)
        own[pid] = bots.income_at(ev, now, first_seen) / shares[pid]
    earners = [own[pid] for pid in ids if count[pid] > 0 and own[pid] > 0]
    prior = statistics.median(earners) if earners else 0.0
    # Only stocks with a results history have a fair price; a brand-new IPO with no results yet has none (no band).
    return {pid: shrunk_income(own[pid], count[pid], prior) for pid in ids if events.get(pid)}, shares


def compute_fair(db: Session, exclude_tournament_ids: list[uuid.UUID] | None = None, at: datetime | None = None) -> dict[uuid.UUID, Decimal]:
    """Fair price for every ACTIVE player right now (or `at`), optionally ignoring some tournaments."""
    inc, shares = income_per_share(db, exclude_tournament_ids, at)
    y = effective_yield(db, inc, shares, live=exclude_tournament_ids is None and at is None)
    return {pid: bots._fair_from_income(v, y) for pid, v in inc.items()}


def solve_target_yield(db: Session, market_value: float) -> float:
    """The target yield at which today's fair prices add up to `market_value` (see market_policy.solve_target_yield)."""
    from app.engine import market_policy

    inc, shares = income_per_share(db)
    pids = list(inc)
    return market_policy.solve_target_yield([inc[p] for p in pids], [shares[p] for p in pids], market_value, bots.FAIR_MIN, bots.FAIR_MAX)


def fair_prices(db: Session, force: bool = False) -> dict[uuid.UUID, Decimal]:
    """Cached fair prices of all active players."""
    now = time.monotonic()
    if not force and _CACHE["fair"] and now - _CACHE["t"] < FAIR_CACHE_SECONDS:
        return _CACHE["fair"]
    fair = compute_fair(db)
    _CACHE.update(t=now, fair=fair)
    return fair


def benchmark(db: Session) -> dict:
    """The market's benchmark growth rate: projected dividends over the next 12 months, per dollar of market value.
    Dividend pools are the only new money the tournaments pour into the game (new players also bring starting cash), so
    a share bought at the going price earns about this much per year from dividends alone; to beat the market you have to
    earn more than this rate."""
    from app.services import reference_service

    fair = fair_prices(db)
    refresh_target_yield(db)
    rows = db.query(Player.id, Player.total_shares_outstanding).filter(Player.is_active.is_(True), Player.id.in_(list(fair.keys()))).all() if fair else []
    refs = reference_service.get_refs(db, [pid for pid, _ in rows])
    fee = float(economic_params_service.get_param(db, "dividend.platform_fee_pct"))
    fee = fee / 100.0 if fee > 1 else fee
    dividends = sum(float(fair[pid]) * bots.TARGET_YIELD * shares for pid, shares in rows) * (1.0 - fee)
    market_value = sum(float(refs.get(pid, fair[pid])) * shares for pid, shares in rows)
    rate = dividends / market_value if market_value > 0 else 0.0
    return {
        "projected_dividends_per_year": round(dividends, 2),
        "market_value": round(market_value, 2),
        "dividend_growth_rate": round(rate, 4),
        "target_yield": bots.TARGET_YIELD,
        "band_low": float(economic_params_service.get_param(db, "market.band_low")),
        "band_high": float(economic_params_service.get_param(db, "market.band_high")),
        "stocks": len(rows),
    }


def fair_for(db: Session, player_id: uuid.UUID) -> Decimal | None:
    return fair_prices(db).get(player_id)


def invalidate() -> None:
    _CACHE.update(t=0.0, fair={})
