from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class ProfileResponse(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    tag: str | None
    tag_color: str | None
    tag_colors: list[str]
    email_verified: bool
    created_at: datetime | None
    name_change_available_at: datetime | None
    name_change_cooldown_days: int
    last_login_at: datetime | None


class DisplayNameRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=100)


class TagRequest(BaseModel):
    tag: str | None = Field(default=None, max_length=10)
    tag_color: str | None = Field(default=None, max_length=9)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class ChangeEmailRequest(BaseModel):
    new_email: EmailStr
    password: str


class DeleteAccountRequest(BaseModel):
    password: str
    confirm: str  # must equal "DELETE"


class SessionRow(BaseModel):
    started_at: datetime
    last_seen_at: datetime
    active_minutes: int
    source: str
    user_agent: str | None
    ip_address: str | None
