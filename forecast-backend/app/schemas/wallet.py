import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.wallet import LedgerEntryType


class DepositRequest(BaseModel):
    """Admin-only (see app/api/v1/wallet.py) -- deposits are no longer
    self-serve so the platform's total money supply stays meaningful
    against the validated economy simulation (every user already gets a
    fixed starting balance automatically at registration -- see
    app/api/v1/auth.py and economic_params_service 'wallet.starting_balance').
    `user_id` defaults to the admin's own wallet if omitted."""

    amount: Decimal = Field(gt=0)
    user_id: uuid.UUID | None = None
    memo: str | None = None


class WithdrawRequest(BaseModel):
    amount: Decimal = Field(gt=0)
    memo: str | None = None


class WalletResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    cash_balance: Decimal
    held_balance: Decimal
    available_balance: Decimal

    model_config = {"from_attributes": True}


class LedgerEntryResponse(BaseModel):
    id: uuid.UUID
    entry_type: LedgerEntryType
    amount: Decimal
    balance_after: Decimal
    reference_type: str | None
    memo: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
