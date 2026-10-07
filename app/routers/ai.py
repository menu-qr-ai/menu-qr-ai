from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.access import Permission
from app.database import get_db
from app.dependencies.access import get_active_restaurant_id
from app.dependencies.auth import require_current_user
from app.models import User
from app.services.access_service import resolve_restaurant_access
from app.services.ai_service import suggest_image_prompt
from app.services.translation_service import translate_dish


router = APIRouter(prefix="/ai", tags=["AI"])


@router.get("/translate-dish/{dish_id}")
def translate_dish_route(
    dish_id: int,
    lang: str = "en",
    db: Session = Depends(get_db),
):
    # Public by design: the customer menu calls it. Cost is bounded because the
    # dish must exist, the language is whitelisted and results are cached.
    return translate_dish(db, dish_id=dish_id, lang=lang)


@router.get("/image-prompt")
def image_prompt(
    current_user: Annotated[User, Depends(require_current_user)],
    active_restaurant_id: Annotated[int | None, Depends(get_active_restaurant_id)],
    dish_name: str = Query(min_length=1, max_length=120),
    style: str = Query(default="modern restaurant", min_length=1, max_length=60),
    restaurant_id: int | None = None,
    db: Session = Depends(get_db),
):
    # Free-text input forwarded to OpenAI: restricted to staff who manage the menu.
    resolve_restaurant_access(
        db,
        current_user,
        restaurant_id,
        Permission.RESTAURANT_MANAGE,
        active_restaurant_id=active_restaurant_id,
    )
    return suggest_image_prompt(dish_name=dish_name, style=style)
