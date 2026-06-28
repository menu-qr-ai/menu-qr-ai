from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from starlette import status

from app.core.exceptions import AppError
from app.database import get_db
from app.services.menu_service import get_menu_data
from app.services.restaurant_service import get_restaurant_by_slug
from app.templates import templates


router = APIRouter()


@router.get("/")
def root():
    return RedirectResponse(url="/menu")


@router.get("/menu")
def menu(request: Request, restaurant_id: int = 1, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request=request,
        name="menu.html",
        context=get_menu_data(db, restaurant_id),
    )


@router.get("/r/{slug}/menu")
def restaurant_menu(slug: str, request: Request, db: Session = Depends(get_db)):
    restaurant = get_restaurant_by_slug(db, slug)
    if restaurant is None or not restaurant.is_active:
        raise AppError(
            "Restaurante no encontrado.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="restaurant_not_found",
        )
    return templates.TemplateResponse(
        request=request,
        name="menu.html",
        context=get_menu_data(db, restaurant.id),
    )
