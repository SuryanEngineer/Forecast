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

import uuid
from datetime import datetime, timezone
from decimal import ROUND_DOWN, Decimal

from sqlalchemy.orm import Session

from app.engine.matching_engine import OrderBook
from app.engine.quick_trade_pricing import (
    SYSTEM_LIQUIDITY_MAKER_ID,
    estimate_quick_order_cost,
    execute_quick_order,
)
from app.engine.types import Fill, Side as EngineSide
from app.models.order import Order, OrderKind, OrderSide, OrderStatus, Trade
from app.models.player import Player, PriceSnapshot
from app.services import book_registry, economic_params_service, position_service, price_feed, wallet_service
from app.services.exceptions import (
    InsufficientFundsError,
    InsufficientSharesError,
    NoLiquidityError,
    OrderNotCancellableError,
    OrderNotFoundError,
    PlayerNotFoundError,
)
from app.services.house_account import get_or_create_house_user


def _get_player_or_raise(db: Session, player_id: uuid.UUID) -> Player:
    player = db.get(Player, player_id)
    if player is None or not player.is_active:
        raise PlayerNotFoundError(str(player_id))
    return player


def _engine_side(side: OrderSide) -> EngineSide:
    return EngineSide.BUY if side == OrderSide.BUY else EngineSide.SELL


def _reference_price(db: Session, player: Player) -> Decimal:
    """Last traded price for this player, falling back to its IPO price if
    it has never traded. Always returns a usable Decimal -- this is what
    guarantees quick orders can always be priced (see NoLiquidityError
    docstring in exceptions.py)."""
    last_snapshot = (
        db.query(PriceSnapshot)
        .filter(PriceSnapshot.player_id == player.id)
        .order_by(PriceSnapshot.recorded_at.desc())
        .first()
    )
    return last_snapshot.price if last_snapshot else player.ipo_price


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
        position_service.transfer_shares_for_trade(db, buyer_owner, seller_owner, player.id, fill_qty, fill.price)

        db.add(PriceSnapshot(id=uuid.uuid4(), player_id=player.id, price=fill.price, volume=fill_qty))
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


def place_limit_order(
    db: Session,
    user_id: uuid.UUID,
    player_id: uuid.UUID,
    side: OrderSide,
    price: Decimal,
    quantity: int,
    is_bot: bool = False,
) -> Order:
    """`is_bot=True` is used exclusively by market_maker_service.py to post
    the House's resting liquidity quotes -- it's still a real Order row
    owned by the House account and still goes through the exact same
    hold/match/settle path as a human's order, it's just tagged so
    trades can distinguish bot-provided liquidity from human liquidity
    for analytics (per roadmap: "bots providing liquidity")."""
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    if price <= 0:
        raise ValueError("price must be positive")

    player = _get_player_or_raise(db, player_id)
    house = get_or_create_house_user(db)
    transaction_fee_pct = economic_params_service.get_param(db, "fees.transaction_fee_pct")

    lock = book_registry.get_player_lock(player_id)
    with lock:
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
        )
        db.add(order)
        db.flush()

        book: OrderBook = book_registry.get_book(db, player_id)
        match = book.add_limit_order(
            order_id=str(order_id), side=_engine_side(side), price=price, quantity=Decimal(quantity), is_bot=is_bot
        )

        _process_fills(db, player, house.id, order, match.fills, transaction_fee_pct=transaction_fee_pct)

    return order


def place_quick_order(db: Session, user_id: uuid.UUID, player_id: uuid.UUID, side: OrderSide, quantity: int, is_bot: bool = False) -> Order:
    if quantity <= 0:
        raise ValueError("quantity must be positive")

    player = _get_player_or_raise(db, player_id)
    house = get_or_create_house_user(db)
    engine_side = _engine_side(side)
    transaction_fee_pct = economic_params_service.get_param(db, "fees.transaction_fee_pct")

    lock = book_registry.get_player_lock(player_id)
    with lock:
        book = book_registry.get_book(db, player_id)
        shares_outstanding = Decimal(player.total_shares_outstanding)
        fallback_price = _reference_price(db, player)

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
        if side == OrderSide.BUY:
            house_position = position_service.get_or_create_position(db, house.id, player_id)
            max_synthetic_quantity = Decimal(house_position.available_quantity)

        estimated_notional = estimate_quick_order_cost(
            book,
            engine_side,
            Decimal(quantity),
            shares_outstanding,
            fallback_reference_price=fallback_price,
            market_impact_coefficient=market_impact_coefficient,
            synthetic_liquidity_depth=synthetic_liquidity_depth,
            max_synthetic_quantity=max_synthetic_quantity,
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
                    f"available balance {wallet.available_balance} is less than estimated cost "
                    f"{estimated_total_with_fee} (including transaction fee)"
                )
        else:
            position = position_service.get_or_create_position(db, user_id, player_id)
            if position.available_quantity < quantity:
                raise InsufficientSharesError(
                    f"user has {position.available_quantity} available shares, needs {quantity}"
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


def cancel_order(db: Session, user_id: uuid.UUID, order_id: uuid.UUID) -> Order:
    order = db.get(Order, order_id)
    if order is None or order.user_id != user_id:
        raise OrderNotFoundError(str(order_id))
    if order.order_kind != OrderKind.LIMIT:
        raise OrderNotCancellableError("quick orders settle instantly and cannot be cancelled")
    if order.status not in (OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED):
        raise OrderNotCancellableError(f"order is already {order.status.value}")

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
