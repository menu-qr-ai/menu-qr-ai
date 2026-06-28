from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.translation_service import translate_dish


router = APIRouter(prefix="/translations", tags=["Translations"])


@router.get("/dish/{dish_id}")
def translate_dish_route(
    dish_id: int,
    lang: str = "en",
    db: Session = Depends(get_db),
):
    return translate_dish(db, dish_id=dish_id, lang=lang)

