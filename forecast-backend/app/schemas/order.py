import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.order import OrderKind, OrderSide, OrderStatus


class LimitOrderRequest(BaseModel):
    player_id: uuid.UUID
    side: OrderSide
    price: Decimal = Field(gt=0)
    quantity: int = Field(gt=0)


class QuickOrderRequest(BaseModel):
    player_id: uuid.UUID
    side: OrderSide
    quantity: int = Field(gt=0)


class OrderResponse(BaseModel):
    id: uuid.UUID
    player_id: uuid.UUID
    side: OrderSide
    order_kind: OrderKind
    limit_price: Decimal | None
    quantity: int
    filled_quantity: int
    status: OrderStatus
    is_bot: bool
    created_at: datetime
    cancelled_at: datetime | None

    model_config = {"from_attributes": True}


class TradeResponse(BaseModel):
    id: uuid.UUID
    player_id: uuid.UUID
    price: Decimal
    quantity: int
    buyer_user_id: uuid.UUID | None
    seller_user_id: uuid.UUID | None
    buyer_is_bot: bool
    seller_is_bot: bool
    executed_at: datetime

    model_config = {"from_attributes": True}
