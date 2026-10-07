from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session
from starlette import status

from app.database import get_db
from app.dependencies.auth import require_current_user
from app.models import User
from app.schemas.category import CategoryCreate, CategoryRead, CategoryUpdate
from app.schemas.dish import DishRead, DishUpdate
from app.services.dish_service import update_dish
from app.services.recipe_management_service import get_recipe_management
from app.services.menu_management_service import (
    create_category,
    delete_category,
    get_menu_management,
    update_category,
)


router = APIRouter(prefix="/api/restaurants/{restaurant_id}", tags=["Menu Management"])


@router.get("/menu-management")
def menu_management_detail(
    restaurant_id: int,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return get_menu_management(db, current_user, restaurant_id)


@router.post(
    "/categories",
    response_model=CategoryRead,
    status_code=status.HTTP_201_CREATED,
)
def category_create(
    restaurant_id: int,
    payload: CategoryCreate,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return create_category(db, current_user, restaurant_id, payload)


@router.patch("/categories/{category_id}", response_model=CategoryRead)
def category_update(
    restaurant_id: int,
    category_id: int,
    payload: CategoryUpdate,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return update_category(db, current_user, restaurant_id, category_id, payload)


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def category_delete(
    restaurant_id: int,
    category_id: int,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    delete_category(db, current_user, restaurant_id, category_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/dishes/{dish_id}", response_model=DishRead)
def dish_update(
    restaurant_id: int,
    dish_id: int,
    payload: DishUpdate,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return update_dish(db, current_user, restaurant_id, dish_id, payload)


@router.get("/recipes")
def recipe_management_detail(
    restaurant_id: int,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return get_recipe_management(db, current_user, restaurant_id)
