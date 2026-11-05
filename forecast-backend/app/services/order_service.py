"""
Order placement, matching, and settlement -- the piece that wires the
pure `app/engine` modules to real database state.

Every public function here (`place_limit_order`, `place_quick_order`,
`cancel_order`) does its work while holding the per-player lock from
`book_registry.py`, so only one order for a given player is ever being
matched at a time (across every request in this process). That lock is
what makes the estimate/execute agreement in quick_trade_pricing.py safe,
and it's also just standard practice for an in-memory order book.

None of these functions call `db.commit()` -- that's the caller's job
(typically the API route, right after the service call returns
successfully), so a failed settlement never leaves a half-written trade.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import ROUND_DOWN, Decimal

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.engine import market_policy
from app.engine.matching_engine import OrderBook
from app.engine.quick_trade_pricing import (
    SYSTEM_LIQUIDITY_MAKER_ID,
    estimate_quick_order_cost,
    estimate_synthetic_leg,
    execute_quick_order,
    worst_sweep_price,
)
from app.engine.types import Fill, Side as EngineSide
from app.models.order import Order, OrderKind, OrderSide, OrderStatus, Trade
from app.models.player import Player, PriceSnapshot
from app.services import (
    book_registry,
    economic_params_service,
    lease_service,
    position_service,
    price_feed,
    reference_service,
    wallet_service,
)
from app.services.exceptions import (
    usd,
    HouseCapacityError,
    InsufficientFundsError,
    InsufficientSharesError,
    NoLiquidityError,
    OrderNotCancellableError,
    OrderNotFoundError,
    PlayerNotFoundError,
    PriceOutOfBandError,
    SelfTradeError,
    ServiceError,
)
from app.services.house_account import get_or_create_house_user


def _get_player_or_raise(db: Session, player_id: uuid.UUID) -> Player:
    player = db.get(Player, player_id)
    if player is None or not player.is_active:
        raise PlayerNotFoundError(str(player_id))
    return player


def _engine_side(side: OrderSide) -> EngineSide:
    return EngineSide.BUY if side == OrderSide.BUY else EngineSide.SELL


class _MarketContext:
    """Everything the pricing rules need for one stock, read once per order (see app/engine/market_policy.py)."""

    def __init__(self, db: Session, player: Player):
        from app.services import fair_price_service  # lazy: fair_price_service imports the bots, which import this module

        self.low = economic_params_service.get_param(db, "market.band_low")
        self.high = economic_params_service.get_param(db, "market.band_high")
        frac = economic_params_service.get_param(db, "market.reference_damping_fraction")
        dmin = economic_params_service.get_param(db, "market.reference_damping_min")
        self.damping_depth = max(Decimal(player.total_shares_outstanding) * frac, dmin)
        self.fair = fair_price_service.fair_for(db, player.id)
        raw = reference_service.get_ref(db, player.id, fallback=player.ipo_price)
        # The reference can sit outside the band after a result moved the fair price; price off the clamped value.
        self.reference = market_policy.clamp_to_band(raw, self.fair, self.low, self.high)
        # Share of this player's supply the House holds (drives its small inventory lean). None if it can't be read.
        self.house_fraction: Decimal | None = None
        try:
            from app.models.player import Position

            house_id = get_or_create_house_user(db).id
            held = db.query(Position.quantity).filter(Position.user_id == house_id, Position.player_id == player.id).scalar()
            if held is not None and player.total_shares_outstanding:
                self.house_fraction = Decimal(int(held)) / Decimal(int(player.total_shares_outstanding))
        except Exception:
            self.house_fraction = None

    def reference_for(self, book: OrderBook, engine_side: EngineSide) -> Decimal:
        """The starting price the House uses for the leg of a quick order it covers: its SELL side for a BUY, its BUY side
        for a SELL. Built from what the real book says (see market_policy.house_quote_refs), not from the slow reference
        alone."""
        bid, ask = book.best_bid, book.best_ask
        bid_ref, ask_ref = market_policy.house_quote_refs(
            self.reference, bid.price if bid else None, ask.price if ask else None, book.last_trade_price, self.house_fraction,
        )
        return ask_ref if engine_side == EngineSide.BUY else bid_ref

    def band(self) -> tuple[Decimal, Decimal] | None:
        if self.fair is None or self.fair <= 0:
            return None
        return market_policy.band_limits(self.fair, self.low, self.high)


def _reference_price(db: Session, player: Player) -> Decimal:
    """The market's reference price for this player (falls back to the IPO price). Always returns a usable Decimal --
    this is what guarantees quick orders can always be priced (see NoLiquidityError docstring in exceptions.py)."""
    return reference_service.get_ref(db, player.id, fallback=player.ipo_price)


_EVENT_CACHE: dict[str, float] = {"checked": 0.0, "active": 0.0}


def _event_window_active(db: Session) -> bool:
    """True while any tournament is about to start (within 2h), is running / started within the last 12h, or finished
    within the last 3h -- the times prices are allowed to move quickly. One tiny query, cached for a minute."""
    now_m = time.monotonic()
    if now_m - _EVENT_CACHE["checked"] < 60.0 and _EVENT_CACHE["checked"]:
        return bool(_EVENT_CACHE["active"])
    from app.models.tournament import Tournament, TournamentStatus

    now = datetime.now(timezone.utc)
    hit = (
        db.query(Tournament.id)
        .filter(
            or_(
                and_(Tournament.start_time >= now - timedelta(hours=12), Tournament.start_time <= now + timedelta(hours=2)),
                and_(Tournament.status == TournamentStatus.FINALIZED, Tournament.updated_at >= now - timedelta(hours=3)),
            )
        )
        .first()
        is not None
    )
    _EVENT_CACHE["checked"] = now_m
    _EVENT_CACHE["active"] = 1.0 if hit else 0.0
    return hit


def _update_reference(db: Session, player: Player, ctx: _MarketContext, fill_price: Decimal, qty: int) -> None:
    current = reference_service.get_ref(db, player.id, fallback=player.ipo_price)
    new = market_policy.reference_after_trade(
        current, fill_price, Decimal(qty), ctx.damping_depth, ctx.fair, ctx.low, ctx.high
    )
    # Calm market: outside tournament windows the reference follows trades only a little per hour.
    cap = economic_params_service.get_param(
        db, "market.event_hourly_move" if _event_window_active(db) else "market.calm_hourly_move"
    )
    new = market_policy.limit_drift(new, reference_service.anchor_price(player.id, current), cap)
    if new.quantize(Decimal("0.0001")) != Decimal(current).quantize(Decimal("0.0001")):
        reference_service.set_ref(db, player.id, new)


_CONSENSUS_STATE: dict[str, float] = {"last": 0.0}
CONSENSUS_INTERVAL_SECONDS = 300.0
CONSENSUS_WINDOW_HOURS = 6


def drift_references_to_trades(db: Session, force: bool = False) -> int:
    """Every few minutes, nudge each stock's slow reference toward what its recent REAL trades say it is worth (see
    market_policy.trade_consensus), so the House's quotes keep tracking actual transactions. The nudge obeys the same
    hourly drift cap and fair-value band as trade-driven updates. Run by the lease holder. Returns stocks moved."""
    now_m = time.monotonic()
    if not force and now_m - _CONSENSUS_STATE["last"] < CONSENSUS_INTERVAL_SECONDS:
        return 0
    _CONSENSUS_STATE["last"] = now_m
    house_id = get_or_create_house_user(db).id
    cutoff = datetime.now(timezone.utc) - timedelta(hours=CONSENSUS_WINDOW_HOURS)
    rows = (
        db.query(Trade.player_id, Trade.price, Trade.quantity, Trade.buyer_user_id, Trade.seller_user_id)
        .filter(
            Trade.executed_at >= cutoff,
            Trade.buyer_user_id.isnot(None),
            Trade.seller_user_id.isnot(None),
            Trade.buyer_user_id != house_id,
            Trade.seller_user_id != house_id,
        )
        .order_by(Trade.executed_at.desc())
        .limit(20000)
        .all()
    )
    by_player: dict[uuid.UUID, list] = {}
    for pid, price, qty, buyer, seller in rows:
        by_player.setdefault(pid, []).append((Decimal(price), int(qty), buyer, seller))
    if not by_player:
        return 0
    cap = economic_params_service.get_param(
        db, "market.event_hourly_move" if _event_window_active(db) else "market.calm_hourly_move"
    )
    moved = 0
    from app.services import fair_price_service

    for player in db.query(Player).filter(Player.id.in_(list(by_player)), Player.is_active.is_(True)).all():
        target = market_policy.trade_consensus(by_player[player.id])
        if target is None:
            continue
        current = reference_service.get_ref(db, player.id, fallback=player.ipo_price)
        low = economic_params_service.get_param(db, "market.band_low")
        high = economic_params_service.get_param(db, "market.band_high")
        new = market_policy.step_toward(current, target)
        new = market_policy.clamp_to_band(new, fair_price_service.fair_for(db, player.id), low, high)
        new = max(market_policy.MIN_PRICE, market_policy.limit_drift(new, reference_service.anchor_price(player.id, current), cap))
        if abs(new - current) >= current * Decimal("0.001"):
            reference_service.set_ref(db, player.id, new)
            moved += 1
    db.commit()
    return moved


def _check_self_trade(db: Session, user_id: uuid.UUID, player_id: uuid.UUID, side: OrderSide, reach: Decimal | None) -> None:
    """Refuse an order that would trade against the same user's own resting order (wash trades fake volume and move the
    reference price). `reach` is the worst price the new order can trade at (its limit price, or the last real level a
    quick order sweeps); None = it can reach everything."""
    opposite = OrderSide.SELL if side == OrderSide.BUY else OrderSide.BUY
    prices = [
        p
        for (p,) in db.query(Order.limit_price)
        .filter(
            Order.user_id == user_id,
            Order.player_id == player_id,
            Order.side == opposite,
            Order.order_kind == OrderKind.LIMIT,
            Order.status.in_([OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED]),
            Order.quantity > Order.filled_quantity,
            Order.limit_price.isnot(None),
        )
        .all()
    ]
    if not prices:
        return
    if reach is None:
        hit = True
    elif side == OrderSide.BUY:
        hit = any(p <= reach for p in prices)
    else:
        hit = any(p >= reach for p in prices)
    if hit:
        raise SelfTradeError("This order would trade against your own resting order for this player -- cancel that order first.")


def _resolve_maker(db: Session, maker_order_id: str, house_user_id: uuid.UUID) -> tuple[uuid.UUID, Order | None]:
    if maker_order_id == SYSTEM_LIQUIDITY_MAKER_ID:
        return house_user_id, None
    maker_order = db.get(Order, uuid.UUID(maker_order_id))
    if maker_order is None:
        # Should never happen -- every resting order in the book has a
        # backing row. Treat as a house fill rather than crash the whole
        # settlement if it somehow does.
        return house_user_id, None
    return maker_order.user_id, maker_order


def _update_order_progress(order: Order, additional_filled_qty: int) -> None:
    order.filled_quantity += additional_filled_qty
    if order.filled_quantity >= order.quantity:
        order.status = OrderStatus.FILLED
    elif order.filled_quantity > 0:
        order.status = OrderStatus.PARTIALLY_FILLED


def _process_fills(
    db: Session,
    player: Player,
    house_user_id: uuid.UUID,
    taker_order: Order,
    fills: list[Fill],
    transaction_fee_pct: Decimal = Decimal("0"),
) -> list[Trade]:
    trades: list[Trade] = []
    total_taker_fill_qty = 0
    taker_notional = Decimal("0")
    ctx = _MarketContext(db, player) if fills else None

    for fill in fills:
        fill_qty = int(fill.quantity)
        total_taker_fill_qty += fill_qty

        if taker_order.side == OrderSide.BUY:
            buyer_owner, buyer_order = taker_order.user_id, taker_order
            seller_owner, seller_order = _resolve_maker(db, fill.maker_order_id, house_user_id)
        else:
            seller_owner, seller_order = taker_order.user_id, taker_order
            buyer_owner, buyer_order = _resolve_maker(db, fill.maker_order_id, house_user_id)

        held_release = None
        if buyer_order is not None and buyer_order.order_kind == OrderKind.LIMIT:
            # The hold placed at order-entry time includes fee headroom
            # (see place_limit_order below), so it must be released with
            # that same headroom regardless of whether this buyer is the
            # taker or the maker in this particular fill -- only the
            # *charge* below is taker-specific, not the hold release.
            held_release = buyer_order.limit_price * fill_qty * (Decimal("1") + transaction_fee_pct)

        # Every fill passed into a single `_process_fills` call shares the
        # same taker (`taker_order` -- either the arriving limit order or
        # the quick order), so the taker's total fee-able notional is just
        # the sum of every fill's notional in this call, regardless of
        # which side (buy or sell) the taker happens to be on.
        taker_notional += fill.price * fill_qty

        buyer_is_bot = buyer_order.is_bot if buyer_order is not None else True
        seller_is_bot = seller_order.is_bot if seller_order is not None else True

        trade = Trade(
            id=uuid.uuid4(),
            player_id=player.id,
            price=fill.price,
            quantity=fill_qty,
            buyer_user_id=buyer_owner,
            seller_user_id=seller_owner,
            buy_order_id=buyer_order.id if buyer_order is not None else None,
            sell_order_id=seller_order.id if seller_order is not None else None,
            buyer_is_bot=buyer_is_bot,
            seller_is_bot=seller_is_bot,
        )
        db.add(trade)
        db.flush()
        trades.append(trade)

        notional = fill.price * fill_qty
        wallet_service.debit_for_trade(db, buyer_owner, notional, trade.id, held_release_amount=held_release)
        wallet_service.credit_for_trade(db, seller_owner, notional, trade.id)
        position_service.transfer_shares_for_trade(
            db, buyer_owner, seller_owner, player.id, fill_qty, fill.price,
            release_seller_hold=seller_order is not None and seller_order.order_kind == OrderKind.LIMIT,
        )

        db.add(PriceSnapshot(id=uuid.uuid4(), player_id=player.id, price=fill.price, volume=fill_qty))
        # The reference price follows trades in proportion to their SIZE (a 1-share trade barely moves it) and never
        # leaves the band around the fair price.
        _update_reference(db, player, ctx, fill.price, fill_qty)
        price_feed.publish_trade(player.id, fill.price, fill_qty)

        # Update the OTHER side's order row if it's a real resting order
        # (the taker's own order is updated once, below, after the loop).
        if buyer_order is not None and buyer_order.id != taker_order.id:
            _update_order_progress(buyer_order, fill_qty)
        if seller_order is not None and seller_order.id != taker_order.id:
            _update_order_progress(seller_order, fill_qty)

    if total_taker_fill_qty > 0:
        _update_order_progress(taker_order, total_taker_fill_qty)

        # Taker-pays transaction fee: charged once per order execution on
        # the taker's total fill notional, credited to the House account
        # as platform revenue. The maker side(s) of every fill above pay
        # nothing -- this is the same "taker pays" convention validated in
        # the economy simulation. Skipped when the taker IS the House
        # (its own bot-liquidity orders never take, only rest -- this
        # guard just avoids a pointless self-transfer if that ever
        # changes) or when the fee rate is zero.
        if transaction_fee_pct > 0 and taker_order.user_id != house_user_id:
            fee_amount = (taker_notional * transaction_fee_pct).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
            if fee_amount > 0:
                wallet_service.charge_fee(db, taker_order.user_id, fee_amount, taker_order.id, memo="Transaction fee")
                wallet_service.receive_fee_revenue(db, house_user_id, fee_amount, taker_order.id, memo="Transaction fee revenue")

    db.flush()
    return trades


def _place_limit_order(
    db: Session,
    user_id: uuid.UUID,
    player_id: uuid.UUID,
    side: OrderSide,
    price: Decimal,
    quantity: int,
    is_bot: bool = False,
    expires_in_minutes: int | None = None,
) -> Order:
    """`expires_in_minutes` (optional) makes the order cancel itself after that long (expire_due_orders); None = good
    until cancelled.

    `is_bot=True` is used exclusively by market_maker_service.py to post
    the House's resting liquidity quotes -- it's still a real Order row
    owned by the House account and still goes through the exact same
    hold/match/settle path as a human's order, it's just tagged so
    trades can distinguish bot-provided liquidity from human liquidity
    for analytics (per roadmap: "bots providing liquidity")."""
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    if price <= 0:
        raise ValueError("price must be positive")
    if price < market_policy.MIN_PRICE:
        raise ValueError(f"minimum share price is ${market_policy.MIN_PRICE}")
    lease_service.require_primary()

    player = _get_player_or_raise(db, player_id)
    house = get_or_create_house_user(db)
    transaction_fee_pct = economic_params_service.get_param(db, "fees.transaction_fee_pct")

    lock = book_registry.get_player_lock(player_id)
    with lock:
        # A limit price must sit inside the band around the stock's fair (dividend-based) value: nobody can post (or
        # accept) a price wildly off what the stock is worth, which is what made wash-trading and "pump" bids possible.
        ctx = _MarketContext(db, player)
        band = ctx.band()
        if band is not None and not market_policy.in_band(price, ctx.fair, ctx.low, ctx.high):
            lo, hi = band
            raise PriceOutOfBandError(
                f"Limit prices for {player.gamertag} must be between ${lo.quantize(Decimal('0.01'))} and "
                f"${hi.quantize(Decimal('0.01'))} (its fair value is about ${ctx.fair.quantize(Decimal('0.01'))})."
            )
        _check_self_trade(db, user_id, player_id, side, price)

        order_id = uuid.uuid4()

        if side == OrderSide.BUY:
            # Hold includes fee headroom up front (price*(1+fee)*qty) so
            # that if/when this order fills -- as either the taker or a
            # resting maker -- there's always enough held to cover the
            # transaction fee without the wallet's cash_balance ever going
            # negative. See _process_fills for the matching release/charge.
            wallet_service.hold_funds(db, user_id, price * quantity * (Decimal("1") + transaction_fee_pct), "order", order_id)
        else:
            position_service.hold_shares(db, user_id, player_id, quantity)

        order = Order(
            id=order_id,
            user_id=user_id,
            player_id=player_id,
            side=side,
            order_kind=OrderKind.LIMIT,
            limit_price=price,
            quantity=quantity,
            filled_quantity=0,
            status=OrderStatus.OPEN,
            is_bot=is_bot,
            expires_at=(datetime.now(timezone.utc) + timedelta(minutes=expires_in_minutes)) if expires_in_minutes else None,
        )
        db.add(order)
        db.flush()

        book: OrderBook = book_registry.get_book(db, player_id)
        match = book.add_limit_order(
            order_id=str(order_id), side=_engine_side(side), price=price, quantity=Decimal(quantity), is_bot=is_bot
        )

        _process_fills(db, player, house.id, order, match.fills, transaction_fee_pct=transaction_fee_pct)

    return order


def _place_quick_order(db: Session, user_id: uuid.UUID, player_id: uuid.UUID, side: OrderSide, quantity: int, is_bot: bool = False) -> Order:
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    lease_service.require_primary()

    player = _get_player_or_raise(db, player_id)
    house = get_or_create_house_user(db)
    engine_side = _engine_side(side)
    transaction_fee_pct = economic_params_service.get_param(db, "fees.transaction_fee_pct")

    lock = book_registry.get_player_lock(player_id)
    with lock:
        book = book_registry.get_book(db, player_id)
        shares_outstanding = Decimal(player.total_shares_outstanding)
        ctx = _MarketContext(db, player)
        # The House quotes around the market's reference price (not the last trade): what a trade costs depends on the
        # reference and its own size, never on whatever tiny trade happened last.
        fallback_price = ctx.reference
        _check_self_trade(db, user_id, player_id, side, worst_sweep_price(book, engine_side, Decimal(quantity)))

        # Read the current tunable slippage/depth parameters from the
        # database (admin-adjustable, see economic_params_service.py)
        # rather than the engine module's hardcoded fallback defaults.
        market_impact_coefficient = economic_params_service.get_param(db, "quick_trade.market_impact_coefficient")
        depth_fraction = economic_params_service.get_param(db, "quick_trade.synthetic_depth_fraction")
        depth_min = economic_params_service.get_param(db, "quick_trade.synthetic_depth_min")
        synthetic_liquidity_depth = max(shares_outstanding * depth_fraction, depth_min)

        # The synthetic (House) leg of a BUY quick order can only ever
        # cover what the House actually still owns of this specific
        # player -- unlike the slippage curve above (an abstract pricing
        # parameter), this is a hard real-inventory cap. Without it, a
        # BUY quick order could "succeed" at the pricing/estimate stage
        # and then crash deep in settlement once the House's real
        # position for this player is fully depleted (see
        # app/engine/quick_trade_pricing.py for the full rationale).
        # SELL orders have no equivalent cap -- the House buying shares
        # back only needs cash, which it's seeded with $10M of.
        max_synthetic_quantity = None
        synthetic_qty, synthetic_notional = estimate_synthetic_leg(
            book, engine_side, Decimal(quantity), shares_outstanding,
            fallback_reference_price=fallback_price,
            market_impact_coefficient=market_impact_coefficient,
            synthetic_liquidity_depth=synthetic_liquidity_depth,
            reference_price_override=ctx.reference_for(book, engine_side),
        )
        if side == OrderSide.BUY:
            house_position = position_service.get_or_create_position(db, house.id, player_id)
            max_synthetic_quantity = Decimal(house_position.available_quantity)
            if synthetic_qty > max_synthetic_quantity:
                can_do = int(Decimal(quantity) - synthetic_qty + max_synthetic_quantity)
                raise HouseCapacityError(
                    f"The House can't sell that many {player.gamertag} shares right now (it has "
                    f"{int(max_synthetic_quantity):,} left to sell). You can buy about {max(0, can_do):,} shares at once -- "
                    f"or place a limit order and wait for a seller."
                )
        elif synthetic_qty > 0:
            # Selling: whatever real bids don't cover, the House pays for in cash. A wallet can't go negative, so a
            # sell bigger than the House's spare cash gets a clear answer instead of a database error.
            house_wallet = wallet_service.get_or_create_wallet(db, house.id)
            if house_wallet.available_balance < synthetic_notional:
                raise HouseCapacityError(
                    f"The House can't buy that many {player.gamertag} shares right now (it would need "
                    f"${synthetic_notional.quantize(Decimal('0.01')):,} and doesn't have that much cash free). "
                    f"Sell fewer shares, or place a limit order and wait for a buyer."
                )

        estimated_notional = estimate_quick_order_cost(
            book,
            engine_side,
            Decimal(quantity),
            shares_outstanding,
            fallback_reference_price=fallback_price,
            market_impact_coefficient=market_impact_coefficient,
            synthetic_liquidity_depth=synthetic_liquidity_depth,
            max_synthetic_quantity=max_synthetic_quantity,
            reference_price_override=ctx.reference_for(book, engine_side),
        )
        if estimated_notional is None:
            raise NoLiquidityError(
                f"not enough real + House liquidity to fill this quick order for player {player_id} "
                f"(House inventory for this player is exhausted -- try a smaller quantity, or wait for "
                f"more real sell-side liquidity)"
            )

        if side == OrderSide.BUY:
            # Fee headroom included in the pre-check (quick orders don't
            # place a hold, so this is the only guard against the fee
            # charge in _process_fills pushing cash_balance negative).
            estimated_total_with_fee = estimated_notional * (Decimal("1") + transaction_fee_pct)
            wallet = wallet_service.get_or_create_wallet(db, user_id)
            if wallet.available_balance < estimated_total_with_fee:
                raise InsufficientFundsError(
                    f"This order would cost about {usd(estimated_total_with_fee)} (including the transaction fee), "
                    f"but you have {usd(wallet.available_balance)} available."
                )
        else:
            position = position_service.get_or_create_position(db, user_id, player_id)
            if position.available_quantity < quantity:
                raise InsufficientSharesError(
                    f"You have {position.available_quantity:,} available share{'' if position.available_quantity == 1 else 's'}, but this order needs {quantity:,}."
                )

        order_id = uuid.uuid4()
        order = Order(
            id=order_id,
            user_id=user_id,
            player_id=player_id,
            side=side,
            order_kind=OrderKind.QUICK,
            limit_price=None,
            quantity=quantity,
            filled_quantity=0,
            status=OrderStatus.OPEN,
            is_bot=is_bot,
        )
        db.add(order)
        db.flush()

        result = execute_quick_order(
            book,
            str(order_id),
            engine_side,
            Decimal(quantity),
            shares_outstanding,
            fallback_reference_price=fallback_price,
            market_impact_coefficient=market_impact_coefficient,
            synthetic_liquidity_depth=synthetic_liquidity_depth,
            max_synthetic_quantity=max_synthetic_quantity,
            reference_price_override=ctx.reference_for(book, engine_side),
        )
        if result.unfilled_quantity > 0:
            # Should not happen given the pre-check above (same book, same
            # lock held throughout) -- but if it ever does, don't leave a
            # dangling half-filled "quick" order sitting open.
            order.status = OrderStatus.REJECTED
            db.flush()
            raise NoLiquidityError(f"could not fully fill quick order for player {player_id}")

        _process_fills(db, player, house.id, order, result.fills, transaction_fee_pct=transaction_fee_pct)

    return order


def quote_quick_order(db: Session, player_id: uuid.UUID, side: OrderSide, quantity: int) -> dict:
    """What a quick order of `quantity` shares would cost / pay RIGHT NOW, worked out exactly the way place_quick_order does
    it: walk the real resting orders best price first, then the House for whatever is left (with its size-dependent
    slippage). Read-only. Money values are returned already rounded to the cent."""
    cent = Decimal("0.01")
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    player = _get_player_or_raise(db, player_id)
    house = get_or_create_house_user(db)
    engine_side = _engine_side(side)
    fee_pct = economic_params_service.get_param(db, "fees.transaction_fee_pct")
    lock = book_registry.get_player_lock(player_id)
    with lock:
        book = book_registry.get_book(db, player_id)
        shares_outstanding = Decimal(player.total_shares_outstanding)
        ctx = _MarketContext(db, player)
        k = economic_params_service.get_param(db, "quick_trade.market_impact_coefficient")
        depth_fraction = economic_params_service.get_param(db, "quick_trade.synthetic_depth_fraction")
        depth_min = economic_params_service.get_param(db, "quick_trade.synthetic_depth_min")
        depth = max(shares_outstanding * depth_fraction, depth_min)
        max_synthetic = None
        if side == OrderSide.BUY:
            max_synthetic = Decimal(position_service.get_or_create_position(db, house.id, player_id).available_quantity)
        notional = estimate_quick_order_cost(
            book, engine_side, Decimal(quantity), shares_outstanding,
            fallback_reference_price=ctx.reference, market_impact_coefficient=k, synthetic_liquidity_depth=depth,
            max_synthetic_quantity=max_synthetic, reference_price_override=ctx.reference_for(book, engine_side),
        )
    out = {"side": side.value, "quantity": quantity, "feasible": notional is not None, "reason": None}
    if notional is None:
        out.update(reason="Not enough shares are available to fill an order this size. Try fewer shares, or use a limit order.",
                   subtotal=None, fee=None, total=None, average_price=None)
        return out
    fee = notional * fee_pct
    total = notional + fee if side == OrderSide.BUY else notional - fee
    out.update(
        subtotal=notional.quantize(cent), fee=fee.quantize(cent), total=total.quantize(cent),
        average_price=(notional / Decimal(quantity)).quantize(cent),
    )
    return out


def place_limit_order(
    db: Session,
    user_id: uuid.UUID,
    player_id: uuid.UUID,
    side: OrderSide,
    price: Decimal,
    quantity: int,
    is_bot: bool = False,
    expires_in_minutes: int | None = None,
) -> Order:
    """See _place_limit_order. An unexpected failure (a database error mid-settlement, say) can leave the in-memory
    book ahead of the rolled-back database, so the cached book is dropped and rebuilt from the database next time.
    Ordinary refusals (funds, band, self-trade, bad input) happen before the book is touched and keep it."""
    try:
        return _place_limit_order(db, user_id, player_id, side, price, quantity, is_bot=is_bot, expires_in_minutes=expires_in_minutes)
    except (ServiceError, ValueError):
        raise
    except Exception:
        book_registry.drop_book(player_id)
        raise


def place_quick_order(db: Session, user_id: uuid.UUID, player_id: uuid.UUID, side: OrderSide, quantity: int, is_bot: bool = False) -> Order:
    """See _place_quick_order (same failure handling as place_limit_order)."""
    try:
        return _place_quick_order(db, user_id, player_id, side, quantity, is_bot=is_bot)
    except (ServiceError, ValueError):
        raise
    except Exception:
        book_registry.drop_book(player_id)
        raise


def cancel_order(db: Session, user_id: uuid.UUID, order_id: uuid.UUID) -> Order:
    lease_service.require_primary()
    order = db.get(Order, order_id)
    if order is None or order.user_id != user_id:
        raise OrderNotFoundError(str(order_id))
    if order.order_kind != OrderKind.LIMIT:
        raise OrderNotCancellableError("quick orders settle instantly and cannot be cancelled")
    if order.status not in (OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED):
        raise OrderNotCancellableError(f"order is already {order.status.value}")
    return _cancel_resting(db, order)


def expire_due_orders(db: Session, now: datetime | None = None, limit: int = 200) -> int:
    """Cancels every open / part-filled limit order whose `expires_at` has passed, releasing its cash or shares exactly like
    a manual cancel. Run every ~20s by the market-lease holder (main._order_expiry_loop). Returns how many were cancelled."""
    now = now or datetime.now(timezone.utc)
    due = (
        db.query(Order)
        .filter(
            Order.expires_at.isnot(None),
            Order.expires_at <= now,
            Order.order_kind == OrderKind.LIMIT,
            Order.status.in_([OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED]),
        )
        .order_by(Order.expires_at.asc())
        .limit(limit)
        .all()
    )
    done = 0
    for order in due:
        try:
            _cancel_resting(db, order)
            db.commit()
            done += 1
        except Exception:  # one bad order must not block the rest; it is retried next sweep
            db.rollback()
    return done


def heal_crossed_books(db: Session, limit: int = 50) -> int:
    """Self-repair for a book that shows resting orders crossing (best bid at or above best ask), which a working market
    never has: crossing orders trade immediately. It can only happen when the database and the in-memory book drifted
    apart (an order failed mid-settlement). For each such player, cancel the bots' crossing orders (releasing their cash
    / shares; the bots simply re-quote next tick) and drop the cached book so it rebuilds from the database. Returns how
    many orders were cancelled. Run by the lease holder alongside order expiry."""
    from sqlalchemy import func

    live = [OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED]
    base = [Order.order_kind == OrderKind.LIMIT, Order.status.in_(live), Order.quantity > Order.filled_quantity, Order.limit_price.isnot(None)]
    rows = (
        db.query(
            Order.player_id,
            func.max(Order.limit_price).filter(Order.side == OrderSide.BUY),
            func.min(Order.limit_price).filter(Order.side == OrderSide.SELL),
        )
        .filter(*base)
        .group_by(Order.player_id)
        .all()
    )
    crossed = [(pid, bid, ask) for pid, bid, ask in rows if bid is not None and ask is not None and bid >= ask][:limit]
    cancelled = 0
    for pid, bid, ask in crossed:
        stale = (
            db.query(Order)
            .filter(
                Order.player_id == pid,
                Order.is_bot.is_(True),
                *base,
                or_(and_(Order.side == OrderSide.BUY, Order.limit_price >= ask), and_(Order.side == OrderSide.SELL, Order.limit_price <= bid)),
            )
            .all()
        )
        for order in stale:
            try:
                _cancel_resting(db, order)
                db.commit()
                cancelled += 1
            except Exception:
                db.rollback()
        book_registry.drop_book(pid)
    return cancelled


_RECONCILE_STATE: dict = {"last": 0.0, "suspect": set()}
RECONCILE_INTERVAL_SECONDS = 120.0
_TOL = Decimal("0.05")


def _open_limit_orders(db: Session, **filters) -> list[Order]:
    live = [OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED]
    q = db.query(Order).filter(
        Order.order_kind == OrderKind.LIMIT, Order.status.in_(live), Order.quantity > Order.filled_quantity, Order.limit_price.isnot(None),
        *[getattr(Order, k) == v for k, v in filters.items()],
    )
    return q.order_by(Order.created_at.asc()).all()


def _buy_need(order: Order, fee: Decimal) -> Decimal:
    return Decimal(order.limit_price) * (order.quantity - order.filled_quantity) * (Decimal("1") + fee)


def _buy_problem(db: Session, uid: uuid.UUID, fee: Decimal):
    """('short'|'excess'|None, orders, need, backing) for one user's resting buys, from fresh database state."""
    from app.models.wallet import Wallet

    w = db.query(Wallet).filter(Wallet.user_id == uid).one_or_none()
    orders = _open_limit_orders(db, user_id=uid, side=OrderSide.BUY)
    need = sum((_buy_need(o, fee) for o in orders), Decimal("0"))
    if w is None:
        return ("short" if orders else None), orders, need, Decimal("0")
    db.refresh(w)
    backing = min(Decimal(w.held_balance), Decimal(w.cash_balance))  # set aside AND actually still there
    if need > backing + _TOL:
        return "short", orders, need, backing
    if Decimal(w.held_balance) > need + _TOL:
        return "excess", orders, need, backing
    return None, orders, need, backing


def _sell_problem(db: Session, uid: uuid.UUID, pid: uuid.UUID):
    from app.models.player import Position

    pos = db.query(Position).filter(Position.user_id == uid, Position.player_id == pid).one_or_none()
    orders = _open_limit_orders(db, user_id=uid, player_id=pid, side=OrderSide.SELL)
    need = sum((o.quantity - o.filled_quantity for o in orders), 0)
    if pos is None:
        return ("short" if orders else None), orders, need, 0, None
    db.refresh(pos)
    backing = min(pos.held_quantity, pos.quantity)
    if need > backing:
        return "short", orders, need, backing, pos
    if pos.held_quantity > need:
        return "excess", orders, need, backing, pos
    return None, orders, need, backing, pos


def reconcile_holds(db: Session, force: bool = False) -> dict[str, int]:
    """Keeps every resting order honest: each open limit BUY must be backed by cash set aside, each open limit SELL by
    shares set aside, so nothing in the book can fail when someone trades against it.

      * wallet.held_balance    should equal  sum(limit price x remaining x (1 + fee)) over the owner's open buys;
      * position.held_quantity should equal  sum(remaining) over the owner's open sells.

    Too LITTLE set aside (cash/shares went elsewhere, or a count drifted) -> cancel that owner's newest orders until the
    rest are fully backed: they leave the book, so nobody sees or trades against an order that cannot be honoured.
    Too MUCH set aside (a stuck reservation) -> release the excess.

    A problem must show up in two sweeps in a row before anything is changed (an order being placed or filled right now can
    look briefly out of step), and is re-checked from fresh data before acting. Run by the lease holder."""
    now_m = time.monotonic()
    if not force and now_m - _RECONCILE_STATE["last"] < RECONCILE_INTERVAL_SECONDS:
        return {"cancelled": 0, "released": 0}
    _RECONCILE_STATE["last"] = now_m

    from app.models.player import Position
    from app.models.wallet import Wallet

    fee = economic_params_service.get_param(db, "fees.transaction_fee_pct")
    orders = _open_limit_orders(db)
    buy_users = {o.user_id for o in orders if o.side == OrderSide.BUY}
    sell_keys = {(o.user_id, o.player_id) for o in orders if o.side == OrderSide.SELL}

    # Candidates: users/positions with orders, plus anything holding a reservation with no orders behind it.
    buy_users |= {uid for (uid,) in db.query(Wallet.user_id).filter(Wallet.held_balance > _TOL).all()}
    sell_keys |= {(u, p) for u, p in db.query(Position.user_id, Position.player_id).filter(Position.held_quantity > 0).all()}

    # Cheap first pass from the rows already loaded (no extra queries) to find who is out of step.
    need_buy: dict = {}
    need_sell: dict = {}
    for o in orders:
        if o.side == OrderSide.BUY:
            need_buy[o.user_id] = need_buy.get(o.user_id, Decimal("0")) + _buy_need(o, fee)
        else:
            k = (o.user_id, o.player_id)
            need_sell[k] = need_sell.get(k, 0) + (o.quantity - o.filled_quantity)
    held_by_user = {u: (Decimal(h), Decimal(c)) for u, h, c in db.query(Wallet.user_id, Wallet.held_balance, Wallet.cash_balance).filter(Wallet.user_id.in_(list(buy_users) or [uuid.uuid4()])).all()}
    held_by_pos = {(u, p): (h, q) for u, p, h, q in db.query(Position.user_id, Position.player_id, Position.held_quantity, Position.quantity).filter(Position.user_id.in_(list({k[0] for k in sell_keys}) or [uuid.uuid4()])).all()}

    suspects: set = set()
    for uid in buy_users:
        held, cash = held_by_user.get(uid, (Decimal("0"), Decimal("0")))
        need = need_buy.get(uid, Decimal("0"))
        if need > min(held, cash) + _TOL or held > need + _TOL:
            suspects.add(("b", uid))
    for k in sell_keys:
        held, qty = held_by_pos.get(k, (0, 0))
        need = need_sell.get(k, 0)
        if need > min(held, qty) or held > need:
            suspects.add(("s", k))

    confirmed = suspects & _RECONCILE_STATE["suspect"]
    _RECONCILE_STATE["suspect"] = suspects - confirmed
    cancelled = released = 0

    def cancel(pool: list[Order], amounts: list[Decimal], backing) -> int:
        n = 0
        for oid in market_policy.orders_to_cancel([(o.id, a) for o, a in zip(pool, amounts)], backing):
            o = next(x for x in pool if x.id == oid)
            try:
                _cancel_resting(db, o)
                db.commit()
                n += 1
            except Exception:
                db.rollback()
            book_registry.drop_book(o.player_id)
        return n

    for kind, key in confirmed:
        try:
            if kind == "b":
                problem, pool, need, backing = _buy_problem(db, key, fee)
                if problem == "short":
                    cancelled += cancel(pool, [_buy_need(o, fee) for o in pool], backing + _TOL)
                    problem, pool, need, backing = _buy_problem(db, key, fee)
                if problem == "excess":
                    excess = Decimal(db.query(Wallet.held_balance).filter(Wallet.user_id == key).scalar()) - need
                    if excess > _TOL:
                        # Relative update: a hold placed a moment ago is not overwritten.
                        db.query(Wallet).filter(Wallet.user_id == key, Wallet.held_balance >= excess).update(
                            {Wallet.held_balance: Wallet.held_balance - excess}, synchronize_session=False)
                        db.commit()
                        released += 1
            else:
                uid, pid = key
                problem, pool, need, backing, pos = _sell_problem(db, uid, pid)
                if problem == "short":
                    cancelled += cancel(pool, [Decimal(o.quantity - o.filled_quantity) for o in pool], Decimal(backing))
                    problem, pool, need, backing, pos = _sell_problem(db, uid, pid)
                if problem == "excess" and pos is not None:
                    excess = pos.held_quantity - need
                    if excess > 0:
                        db.query(Position).filter(Position.user_id == uid, Position.player_id == pid, Position.held_quantity >= excess).update(
                            {Position.held_quantity: Position.held_quantity - excess}, synchronize_session=False)
                        db.commit()
                        released += 1
        except Exception:
            db.rollback()
    return {"cancelled": cancelled, "released": released}


def _cancel_resting(db: Session, order: Order) -> Order:
    """Takes a resting limit order off the book and releases what it was holding (shared by cancel and expiry)."""
    user_id = order.user_id
    lock = book_registry.get_player_lock(order.player_id)
    with lock:
        book = book_registry.get_book(db, order.player_id)
        book.cancel(str(order.id))

        remaining_qty = order.quantity - order.filled_quantity
        if order.side == OrderSide.BUY:
            # Hold was placed with fee headroom (see place_limit_order),
            # so it must be released with that same headroom or a sliver
            # of cash would stay stuck in held_balance forever. NOTE: if an
            # admin changes fees.transaction_fee_pct while this order is
            # still resting, this uses the CURRENT rate, not the rate in
            # effect at placement time -- release_hold's clamp to
            # wallet.held_balance keeps this safe (never goes negative),
            # but a rate change mid-flight could over/under-release by a
            # few cents on any order placed before the change. Storing the
            # rate on the Order row at placement time would close that gap
            # completely; not done here since fee-rate changes are rare
            # admin actions, not part of normal trading.
            transaction_fee_pct = economic_params_service.get_param(db, "fees.transaction_fee_pct")
            wallet_service.release_hold(
                db, user_id, order.limit_price * remaining_qty * (Decimal("1") + transaction_fee_pct), "order", order.id
            )
        else:
            position_service.release_shares(db, user_id, order.player_id, remaining_qty)

        order.status = OrderStatus.CANCELLED
        order.cancelled_at = datetime.now(timezone.utc)
        db.flush()

    return order
