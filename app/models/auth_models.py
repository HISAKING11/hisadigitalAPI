from pydantic import BaseModel
from typing import Literal, Optional

class RegisterRequest(BaseModel):
    name: str
    email: str
    phone: str
    password: str
    confirm_password: str
    account_type: Optional[Literal["user", "author"]] = None


class LoginRequest(BaseModel):
    email: str
    password: str


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class UpdateProfileRequest(BaseModel):
    name: str
    phone: str


class UpdateEmailRequest(BaseModel):
    new_email: str


class UpdatePasswordRequest(BaseModel):
    current_password: str
    new_password: str
