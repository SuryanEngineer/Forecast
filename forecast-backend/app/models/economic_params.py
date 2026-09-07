"""
Admin-tunable economic parameters. These exist specifically so that
things like the quick-buy/sell slippage steepness, the bot market-maker's
spread/ladder, the dividend platform fee, and the placement payout curve
can all be changed from the admin API / a future admin dashboard --
WITHOUT a code deploy. Every value has a hardcoded fallback (see
DEFAULTS in app/services/economic_params_service.py and the module-level
constants in app/engine/*.py) so the system works out of the box, but
every one of those defaults is meant to be tuned once the simulation
phase of the roadmap (or real usage) tells you what the right numbers
are.
"""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import GUID


class PlatformParameter(Base):
    """One named scalar knob. `key` is a dotted namespace, e.g.
    'quick_trade.market_impact_coefficient' or 'bot_liquidity.spread_pct'
    -- see economic_params_service.DEFAULTS for the full list and what
    each one controls."""

    __tablename__ = "platform_parameters"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("users.id"), nullable=True)


class DividendPlacementCurveEntry(Base):
    """One row of the default placement -> pool-fraction payout curve
    used by app/engine/dividend_calculator.py whenever an admin hasn't
    entered an exact `prize_won` for a placement. Admin-editable so the
    curve can be corrected to match how a given tournament actually pays
    out without a code change."""

    __tablename__ = "dividend_placement_curve"

    placement: Mapped[int] = mapped_column(Integer, primary_key=True)
    pool_fraction: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
