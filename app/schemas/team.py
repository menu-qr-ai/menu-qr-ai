import re

from pydantic import BaseModel, Field, field_validator

from app.core.access import RestaurantRole

# Deliberately permissive: the goal is catching typos, not validating RFC 5322.
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LENGTH = 10


class TeamMemberCreate(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    full_name: str | None = Field(default=None, max_length=120)
    role: RestaurantRole

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not EMAIL_PATTERN.match(normalized):
            raise ValueError("Escribe un email válido, por ejemplo nombre@restaurante.com.")
        return normalized

    @field_validator("full_name")
    @classmethod
    def normalize_full_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        return normalized or None


class TeamMemberRead(BaseModel):
    membership_id: int
    user_id: int
    email: str
    full_name: str | None
    role: RestaurantRole
    is_active: bool
    is_self: bool
    can_reset_password: bool


class TeamMemberCreated(BaseModel):
    member: TeamMemberRead
    created_account: bool
    # Shown once to the owner so they can hand it over; never stored in clear.
    temporary_password: str | None = None


class TemporaryPasswordRead(BaseModel):
    member: TeamMemberRead
    temporary_password: str


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=1024)
