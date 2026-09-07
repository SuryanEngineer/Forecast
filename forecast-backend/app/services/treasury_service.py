"""
Treasury instrument: purchase, redeem, and daily accrual.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.config import settings
from app.engine.treasury_calculator import accrue_interest, redemption_value
from app.models.treasury import TreasuryAccrualLog, TreasuryHolding, TreasuryHoldingStatus, TreasuryInstrument
from app.services import wallet_service
from app.services.exceptions import ServiceError


class TreasuryInstrumentNotFoundError(ServiceError):
    pass


class TreasuryHoldingNotFoundError(ServiceError):
    pass


def get_or_create_active_instrument(db: Session, annual_rate: Decimal | None = None) -> TreasuryInstrument:
    """Returns the current active instrument, creating the very first one
    (at `settings.DEFAULT_TREASURY_ANNUAL_RATE`) if none exists yet."""
    instrument = (
        db.query(TreasuryInstrument)
        .filter(TreasuryInstrument.is_active.is_(True))
        .order_by(TreasuryInstrument.effective_from.desc())
        .first()
    )
    if instrument is not None:
        return instrument

    instrument = TreasuryInstrument(
        id=uuid.uuid4(),
        name="Forecast T-Bill",
        annual_rate=annual_rate if annual_rate is not None else Decimal(str(settings.DEFAULT_TREASURY_ANNUAL_RATE)),
        is_active=True,
        effective_from=date.today(),
    )
    db.add(instrument)
    db.flush()
    return instrument


def set_new_rate(db: Session, new_annual_rate: Decimal, effective_from: date | None = None) -> TreasuryInstrument:
    """Admin/simulation lever: change the going-forward treasury rate.
    Deactivates the old instrument row and inserts a new one -- existing
    holdings keep accruing, just at the new rate from here on (accrual
    always uses whichever instrument was active on the day it runs)."""
    current = db.query(TreasuryInstrument).filter(TreasuryInstrument.is_active.is_(True)).one_or_none()
    if current is not None:
        current.is_active = False

    new_instrument = TreasuryInstrument(
        id=uuid.uuid4(),
        name=current.name if current is not None else "Forecast T-Bill",
        annual_rate=new_annual_rate,
        is_active=True,
        effective_from=effective_from or date.today(),
    )
    db.add(new_instrument)
    db.flush()
    return new_instrument


def purchase(db: Session, user_id: uuid.UUID, amount: Decimal) -> TreasuryHolding:
    if amount <= 0:
        raise ValueError("purchase amount must be positive")
    instrument = get_or_create_active_instrument(db)

    holding_id = uuid.uuid4()
    wallet_service.debit_for_treasury_purchase(db, user_id, amount, holding_id)

    holding = TreasuryHolding(
        id=holding_id,
        user_id=user_id,
        treasury_instrument_id=instrument.id,
        principal_amount=amount,
        accrued_interest=Decimal("0"),
        status=TreasuryHoldingStatus.ACTIVE,
    )
    db.add(holding)
    db.flush()
    return holding


def redeem(db: Session, user_id: uuid.UUID, holding_id: uuid.UUID) -> TreasuryHolding:
    holding = db.get(TreasuryHolding, holding_id)
    if holding is None or holding.user_id != user_id:
        raise TreasuryHoldingNotFoundError(str(holding_id))
    if holding.status != TreasuryHoldingStatus.ACTIVE:
        raise ServiceError(f"holding {holding_id} is already {holding.status.value}")

    total = redemption_value(holding.principal_amount, holding.accrued_interest)
    wallet_service.credit_for_treasury_redemption(db, user_id, total, holding.id)

    holding.status = TreasuryHoldingStatus.REDEEMED
    holding.redeemed_at = datetime.now(timezone.utc)
    db.flush()
    return holding


def accrue_all_active_holdings(db: Session, days_elapsed: Decimal = Decimal("1")) -> int:
    """Meant to be run once per day by app/jobs/tasks.py:accrue_treasury_job.
    Returns the number of holdings accrued. Each holding accrues against
    whichever TreasuryInstrument it was purchased under -- if the admin
    has since changed the rate via `set_new_rate`, existing holdings keep
    their original instrument's rate unless you explicitly migrate them
    (not implemented in v1 -- simplest correct behavior: rate changes
    apply to NEW purchases only, matching how real bond series work)."""
    holdings = db.query(TreasuryHolding).filter(TreasuryHolding.status == TreasuryHoldingStatus.ACTIVE).all()
    count = 0
    for holding in holdings:
        instrument = db.get(TreasuryInstrument, holding.treasury_instrument_id)
        interest = accrue_interest(holding.principal_amount, instrument.annual_rate, days_elapsed)
        if interest <= 0:
            continue
        holding.accrued_interest += interest
        holding.last_accrued_at = datetime.now(timezone.utc)
        db.add(TreasuryAccrualLog(id=uuid.uuid4(), holding_id=holding.id, amount=interest))
        count += 1
    db.flush()
    return count
