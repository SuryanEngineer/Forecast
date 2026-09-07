"""
Bot-provided liquidity, per the roadmap's simulation design ("bots
providing liquidity" is one of the factors the chapter-length simulation
tests for market stability).

*** PLACEHOLDER STRATEGY -- read this before trusting the numbers ***
This is intentionally the simplest possible market maker: post a
symmetric ladder of resting bid/ask limit orders from the House account
around a center price, stepping outward by a fixed percentage per level.
It does not react to inventory skew, volatility, or time -- it's a
starting point so every player has *some* tradeable liquidity from the
moment it IPOs, not a tuned trading bot. The simulation phase of the
roadmap is the right place to design a more realistic bot (e.g. one that
widens its spread after taking on inventory, or pulls quotes around
tournament result announcements) -- swap that logic in here without
touching order_service.py, which doesn't care who placed an order.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.order import OrderSide
from app.models.player import Player
from app.services import economic_params_service, order_service
from app.services.house_account import get_or_create_house_user


def post_bot_quotes(
    db: Session,
    player: Player,
    center_price: Decimal | None = None,
    num_levels: int | None = None,
    step_pct: Decimal | None = None,
    spread_pct: Decimal | None = None,
    qty_per_level: int | None = None,
) -> None:
    """Post a fresh ladder of House bid/ask orders around `center_price`
    (defaults to the player's IPO price). Typically called once right
    after `player_service.create_player`, and can be re-run periodically
    (e.g. from a scheduled job) to refresh liquidity around the latest
    price -- this function does not cancel previous bot orders first, so
    calling it repeatedly without a refresh/cancel step will stack up
    orders; wiring that refresh cadence is a good next step once the
    simulation defines how often liquidity should be refreshed.

    Any of `num_levels`/`step_pct`/`spread_pct`/`qty_per_level` left as
    `None` are read from the admin-adjustable `platform_parameters` table
    (see economic_params_service.py, keys `bot_liquidity.*`) instead of a
    hardcoded constant -- change them via the admin API and the very next
    call to this function picks up the new values, no deploy needed."""
    house = get_or_create_house_user(db)
    center = center_price if center_price is not None else player.ipo_price

    if num_levels is None:
        num_levels = int(economic_params_service.get_param(db, "bot_liquidity.num_levels"))
    if step_pct is None:
        step_pct = economic_params_service.get_param(db, "bot_liquidity.step_pct")
    if spread_pct is None:
        spread_pct = economic_params_service.get_param(db, "bot_liquidity.spread_pct")
    if qty_per_level is None:
        qty_per_level = int(economic_params_service.get_param(db, "bot_liquidity.qty_per_level"))

    for level in range(1, num_levels + 1):
        bid_offset = spread_pct + step_pct * (level - 1)
        ask_offset = spread_pct + step_pct * (level - 1)
        bid_price = (center * (Decimal("1") - bid_offset)).quantize(Decimal("0.0001"))
        ask_price = (center * (Decimal("1") + ask_offset)).quantize(Decimal("0.0001"))

        if bid_price > 0:
            order_service.place_limit_order(
                db, house.id, player.id, OrderSide.BUY, bid_price, qty_per_level, is_bot=True
            )
        order_service.place_limit_order(
            db, house.id, player.id, OrderSide.SELL, ask_price, qty_per_level, is_bot=True
        )
