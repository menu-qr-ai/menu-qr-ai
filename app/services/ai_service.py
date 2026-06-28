from sqlalchemy.orm import Session

from app.services.image_service import generate_dish_image_prompt
from app.services.translation_service import translate_dish as translate_dish_service


def translate_dish(db: Session, dish_id: int, lang: str = "en") -> dict:
    return translate_dish_service(db, dish_id=dish_id, lang=lang)


def suggest_image_prompt(dish_name: str, style: str = "modern restaurant") -> dict:
    return generate_dish_image_prompt(dish_name=dish_name, style=style)
