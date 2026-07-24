from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.models import User


_DUMMY_PASSWORD_HASH = hash_password(
    "hostai-dummy-password-never-used-for-login"
)


def get_user_by_email(db: Session, email: str) -> User | None:
    normalized_email = email.strip().lower()
    return db.scalar(select(User).where(func.lower(User.email) == normalized_email))


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    user = get_user_by_email(db, email)
    encoded_password = (
        user.hashed_password
        if user is not None and user.is_active
        else _DUMMY_PASSWORD_HASH
    )
    password_matches = verify_password(password, encoded_password)
    if user is None or not user.is_active or not password_matches:
        return None
    return user
