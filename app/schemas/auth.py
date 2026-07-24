from pydantic import BaseModel, Field, field_validator

from app.schemas.user import UserRead


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class AuthenticatedUserRead(BaseModel):
    user: UserRead
    next_url: str = "/app"
    csrf_token: str | None = None
