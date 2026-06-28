from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.models import Dish, Translation
from app.services.openai_service import openai_service
from app.schemas.translation import SUPPORTED_LANGUAGES


def _normalize_language(lang: str) -> str:
    normalized = (lang or "en").strip().lower()
    return normalized if normalized in SUPPORTED_LANGUAGES else "en"


def _cached_translation(db: Session, dish_id: int, lang: str) -> dict | None:
    try:
        translation = db.scalar(
            select(Translation)
            .where(Translation.dish_id == dish_id, Translation.language == lang)
            .order_by(Translation.id.desc())
        )
    except OperationalError:
        db.rollback()
        return None

    if not translation:
        return None
    return {
        "name": translation.name,
        "description": translation.description or "",
        "ingredients": translation.ingredients or "",
        "allergens": translation.allergens or "",
        "cached": True,
    }


def _save_translation(db: Session, dish_id: int, lang: str, payload: dict) -> None:
    if payload.get("error"):
        return
    try:
        db.add(
            Translation(
                dish_id=dish_id,
                language=lang,
                name=payload.get("name") or "",
                description=payload.get("description") or "",
                ingredients=payload.get("ingredients") or "",
                allergens=payload.get("allergens") or "",
            )
        )
        db.commit()
    except OperationalError:
        db.rollback()


def translate_dish(db: Session, dish_id: int, lang: str = "en") -> dict:
    lang = _normalize_language(lang)
    dish = db.scalar(select(Dish).where(Dish.id == dish_id))
    if not dish:
        return {"error": "Dish not found"}

    cached = _cached_translation(db, dish_id, lang)
    if cached:
        return cached

    prompt = f"""
Translate this restaurant dish to {lang}.

Name: {dish.name}
Description: {dish.description or ""}
Ingredients: {dish.ingredients or ""}
Allergens: {dish.allergens or ""}

Return only valid JSON with these keys:
name, description, ingredients, allergens.
"""

    result = openai_service.json_completion(
        system="You are a restaurant menu translator.",
        prompt=prompt,
    )
    _save_translation(db, dish_id, lang, result)
    return result


def translate_text(text: str, lang: str = "en") -> dict:
    lang = _normalize_language(lang)
    return openai_service.json_completion(
        system="You translate restaurant content and return JSON.",
        prompt=f'Translate this text to {lang} and return JSON with key "text": {text}',
    )
