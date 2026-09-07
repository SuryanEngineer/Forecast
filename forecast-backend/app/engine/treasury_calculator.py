"""
Treasury instrument accrual.

*** PLACEHOLDER FORMULA -- read this before trusting the numbers ***
Roadmap calls this "treasury instrument" without specifying the exact
mechanics, so this implements the simplest realistic version: a
money-market-style instrument, redeemable any time, accruing simple daily
interest at a rate the admin can change over time (each rate change is a
new `TreasuryInstrument` row with an `effective_from` date -- see
app/models/treasury.py -- so historical accrual is always computed with
the rate that was actually in effect, and the admin/simulation gets a
lever to raise or lower the rate as an inflation control, per the
project's simulation goals).

Interest is simple (not compounded) per accrual period:
    interest = principal * annual_rate * (days_elapsed / 365)

Each time the accrual job runs (see app/jobs/tasks.py) it adds one day's
interest to `accrued_interest` and rolls `principal` forward by adding
that interest to it for the *next* period's calculation -- i.e. daily
compounding in practice, even though each individual period is computed
with simple interest. This keeps the math easy to audit line-by-line in
the TreasuryAccrualLog while still compounding over time.
"""
from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

CENT = Decimal("0.01")
DAYS_PER_YEAR = Decimal("365")


def accrue_interest(principal: Decimal, annual_rate: Decimal, days_elapsed: Decimal = Decimal("1")) -> Decimal:
    """Interest earned on `principal` over `days_elapsed` days at
    `annual_rate` (e.g. Decimal("0.04") for 4% APY). Rounded down to the
    cent so the platform never pays out a fractional cent it doesn't
    later collect back in rounding."""
    if principal <= 0 or annual_rate <= 0 or days_elapsed <= 0:
        return Decimal("0.00")
    interest = principal * annual_rate * (days_elapsed / DAYS_PER_YEAR)
    return interest.quantize(CENT, rounding=ROUND_DOWN)


def redemption_value(principal: Decimal, accrued_interest: Decimal) -> Decimal:
    return principal + accrued_interest
