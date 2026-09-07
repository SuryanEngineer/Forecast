"""
The "House" / market-maker account.

Every player IPOs with 100% of its shares owned by the House. Real users
buy shares away from the House (via the House's own resting bid/ask
orders -- see market_maker_service.py, this is the roadmap's "bots
providing liquidity") and can sell shares back to it. The synthetic
fallback fill in quick_trade_pricing.py is also, conceptually, "the House
sells you shares out of its own inventory at a markup" -- which is why
routing it through a real account (rather than conjuring shares/cash out
of nowhere) keeps total shares outstanding and total cash in the system
exactly conserved and auditable like every other account.

The House is seeded with a large (but finite, configurable) cash reserve
so it can act as buyer of last resort on the sell side. If it depletes,
that's a real, visible signal in the simulation (the platform's synthetic
liquidity is undercapitalized) rather than a silently-ignored bug -- see
README_SETUP.md for how to top it up.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.user import User, UserRole
from app.services import wallet_service

HOUSE_ACCOUNT_EMAIL = "house@system.forecast.internal"
DEFAULT_HOUSE_SEED_CASH = Decimal("10000000.0000")  # $10,000,000 starting reserve, configurable


def get_or_create_house_user(db: Session, seed_cash: Decimal = DEFAULT_HOUSE_SEED_CASH) -> User:
    house = db.query(User).filter(User.email == HOUSE_ACCOUNT_EMAIL).one_or_none()
    if house is not None:
        return house

    house = User(
        email=HOUSE_ACCOUNT_EMAIL,
        password_hash="!disabled!",  # this account can never log in
        display_name="House Liquidity Account",
        role=UserRole.ADMIN,
        is_active=True,
    )
    db.add(house)
    db.flush()

    wallet_service.get_or_create_wallet(db, house.id)
    wallet_service.deposit(db, house.id, seed_cash, memo="Initial house liquidity seed")
    return house
