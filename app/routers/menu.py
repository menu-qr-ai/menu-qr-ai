from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.menu_service import get_menu_data
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
