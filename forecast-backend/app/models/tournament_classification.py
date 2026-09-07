"""
Two small admin-tunable tables that back "automatic tournament tracking"
(see app/services/osirion_service.auto_track_new_tournaments):

- TournamentClassificationRule: a pattern -> tier mapping used to decide,
  for every window Osirion currently has open, whether to auto-track it at
  all and if so as which TournamentType. A rule with tournament_type=NULL
  means "exclude" -- matching windows are never auto-tracked (this is how
  Victory Cups / skin cups / anything else not explicitly wanted gets kept
  out without a human having to notice and reject each one).

  Matching is a case-insensitive substring test against the Osirion
  window's display name (see osirion_service._display_name), tried in
  `priority` order (lowest first); the first match wins. A window that
  matches NO rule is left alone (not auto-tracked, not excluded) --
  auto-tracking is deliberately a whitelist, not a "track everything
  except known junk" blocklist, since guessing wrong on an unrecognized
  tournament name means either a bad payout tier or an accidental
  real-money-shaped dividend for something that shouldn't have one.

- RegionMultiplier: a per-region scale factor applied on top of a tier's
  fixed dividend pool (see economic_params_service.FIXED_POOL_PARAM_BY_TOURNAMENT_TYPE)
  before it's split among shareholders, e.g. an EU Cash Cup and an OCE
  Cash Cup both start from `dividend.cash_cup_pool` but the OCE one pays
  out a smaller absolute amount, matching that region's smaller
  competitive scene. `DEFAULT_REGION_KEY` is the fallback multiplier used
  for any region string that doesn't have its own row (including no
  region at all).
"""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import GUID
from app.models.tournament import TournamentType

# Fallback row key for any region string with no explicit RegionMultiplier
# row (also used for tournaments with no region set at all).
DEFAULT_REGION_KEY = "DEFAULT"


class TournamentClassificationRule(Base):
    __tablename__ = "tournament_classification_rules"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    pattern: Mapped[str] = mapped_column(String(200), nullable=False)
    # NULL = exclude (never auto-track a window matching this pattern).
    tournament_type: Mapped[TournamentType | None] = mapped_column(
        SAEnum(TournamentType, name="tournament_type", native_enum=True, values_callable=lambda obj: [e.value for e in obj]),
        nullable=True,
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RegionMultiplier(Base):
    __tablename__ = "region_multipliers"

    region: Mapped[str] = mapped_column(String(50), primary_key=True)
    multiplier: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
