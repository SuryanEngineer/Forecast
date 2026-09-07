import uuid
from decimal import Decimal

from pydantic import BaseModel


class LeaderboardEntryResponse(BaseModel):
    rank: int
    user_id: uuid.UUID
    display_name: str
    cash_balance: Decimal
    holdings_value: Decimal
    portfolio_value: Decimal
