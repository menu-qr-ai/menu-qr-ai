from datetime import datetime

from app.schemas.common import ORMModel


class QRCodeRead(ORMModel):
    id: int
    restaurant_id: int
    target_url: str
    image_path: str | None = None
    status: str
    created_at: datetime
