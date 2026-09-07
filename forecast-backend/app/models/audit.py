import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy import func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import GUID, JSONType


class ActorType(str, enum.Enum):
    USER = "user"
    ADMIN = "admin"
    SYSTEM = "system"
    BOT = "bot"


class AuditLog(Base):
    """
    General-purpose audit trail for anything that isn't a wallet balance
    change (those go in LedgerEntry instead, which is money-specific and
    append-only in the same way). Use this for: order placed/cancelled,
    admin entered/edited a placement result, treasury rate changed, admin
    login, etc. `metadata_json` is a free-form JSONB blob -- keep it
    small and specific to the action, don't dump entire request bodies.
    """

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    actor_type: Mapped[ActorType] = mapped_column(
        SAEnum(ActorType, name="actor_type", native_enum=True, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    entity_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSONType(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
