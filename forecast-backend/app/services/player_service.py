"""
Player creation ("IPO"). Creating a Player is the one place shares get
minted: the House account is given a Position equal to 100% of
`total_shares_outstanding` at creation time, and everything after that is
just shares moving between accounts via trades -- no share is ever
created or destroyed after IPO (see position_service.py).
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.player import Player
from app.services.house_account import get_or_create_house_user
from app.services.position_service import get_or_create_position


def ipo_price_for_rating(power_rating: int) -> Decimal:
    """$40 base at rating 50, +/- $2 per rating point either side -- e.g.
    a rating-97 elite pro IPOs around $134, a rating-65 journeyman around
    $70. Ported as-is from the standalone browser build's bootstrap.ts,
    which validated this scaling against the full seeded roster. Keeps an
    elite player commanding a real premium over a journeyman from day one
    instead of every IPO starting at an identical flat price."""
    return Decimal(40 + (power_rating - 50) * 2).quantize(Decimal("0.01"))


def create_player(
    db: Session,
    gamertag: str,
    real_name: str | None = None,
    team: str | None = None,
    region: str | None = None,
    total_shares_outstanding: int = 10_000,
    ipo_price: Decimal | None = None,
    power_rating: int = 65,
) -> Player:
    house = get_or_create_house_user(db)

    # An explicit admin-entered ipo_price always wins (e.g. for a player
    # being IPO'd via auction_service.py's clearing-price flow, or an
    # admin who wants to hand-tune one player's price) -- power_rating
    # only supplies the default when no explicit price was given.
    resolved_ipo_price = ipo_price if ipo_price is not None else ipo_price_for_rating(power_rating)

    player = Player(
        id=uuid.uuid4(),
        gamertag=gamertag,
        real_name=real_name,
        team=team,
        region=region,
        total_shares_outstanding=total_shares_outstanding,
        ipo_price=resolved_ipo_price,
        power_rating=power_rating,
        is_active=True,
    )
    db.add(player)
    db.flush()

    house_position = get_or_create_position(db, house.id, player.id)
    house_position.quantity = total_shares_outstanding
    house_position.average_cost = Decimal("0")
    db.flush()

    return player
