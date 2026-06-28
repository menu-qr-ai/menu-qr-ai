from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.ai_service import suggest_image_prompt
from app.services.translation_service import translate_dish


router = APIRouter(prefix="/ai", tags=["AI"])


@router.get("/translate-dish/{dish_id}")
def translate_dish_route(
    dish_id: int,
    lang: str = "en",
    db: Session = Depends(get_db),
):
    return translate_dish(db, dish_id=dish_id, lang=lang)


@router.get("/image-prompt")
def image_prompt(dish_name: str, style: str = "modern restaurant"):
    return suggest_image_prompt(dish_name=dish_name, style=style)
