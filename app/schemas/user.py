from datetime import datetime

from app.schemas.common import ORMModel


class UserRead(ORMModel):
    id: int
    email: str
    full_name: str | None = None
    is_active: bool = True
    created_at: datetime
