import uuid

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    display_name: str = Field(min_length=1, max_length=100)


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

    model_config = {"from_attributes": True}


class PasswordResetRequestRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirmRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8)


class MessageResponse(BaseModel):
    message: str
