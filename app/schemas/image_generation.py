from datetime import datetime

from app.schemas.common import ORMModel


class ImageGenerationRead(ORMModel):
    id: int
    dish_id: int | None = None
    prompt: str
    image_url: str | None = None
    provider: str
    status: str
    created_at: datetime
