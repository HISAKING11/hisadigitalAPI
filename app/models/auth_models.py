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
