import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=100)
    accept_terms: bool = False


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: uuid.UUID


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    role: str
    tag: str | None = None
    tag_color: str | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class PasswordResetRequestRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirmRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=4, max_length=10)
    new_password: str = Field(min_length=8, max_length=128)


class CodeRequest(BaseModel):
    code: str = Field(min_length=4, max_length=10)


class MessageResponse(BaseModel):
    message: str
