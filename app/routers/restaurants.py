from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from starlette import status

from app.core.access import Permission
from app.core.exceptions import AppError
from app.database import get_db
from app.dependencies.auth import require_current_user
from app.models import User
from app.schemas.costing import DishCosting, DishCostingList
from app.schemas.dish import DishCreate, DishPriceUpdate, DishRead
from app.schemas.restaurant import RestaurantCreate, RestaurantRead, RestaurantUpdate
from app.services.costing_service import get_dish_costing, list_dish_costings
from app.services.dish_service import create_dish, update_dish_price
from app.services.access_service import (
    authorize_restaurant,
    create_restaurant_with_owner,
    list_user_memberships,
)
from app.services.restaurant_service import (
    get_restaurant_by_slug,
    require_restaurant,
    update_restaurant,
)


router = APIRouter(prefix="/api/restaurants", tags=["Restaurants"])


@router.get("", response_model=list[RestaurantRead])
def restaurants_index(
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return [membership.restaurant for membership in list_user_memberships(db, current_user.id)]


@router.get("/{restaurant_id}", response_model=RestaurantRead)
def restaurant_detail(
    restaurant_id: int,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    authorize_restaurant(db, current_user, restaurant_id, Permission.RESTAURANT_READ)
    return require_restaurant(db, restaurant_id)


@router.get("/{restaurant_id}/dishes/{dish_id}/costing", response_model=DishCosting)
def restaurant_dish_costing(
    restaurant_id: int,
    dish_id: int,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    authorize_restaurant(db, current_user, restaurant_id, Permission.COSTING_READ)
    return get_dish_costing(db, restaurant_id, dish_id)


@router.post(
    "/{restaurant_id}/dishes",
    response_model=DishRead,
    status_code=status.HTTP_201_CREATED,
)
def restaurant_dish_create(
    restaurant_id: int,
    payload: DishCreate,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return create_dish(db, current_user, restaurant_id, payload)


@router.patch(
    "/{restaurant_id}/dishes/{dish_id}/price",
    response_model=DishRead,
)
def restaurant_dish_price_update(
    restaurant_id: int,
    dish_id: int,
    payload: DishPriceUpdate,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return update_dish_price(
        db,
        current_user,
        restaurant_id,
        dish_id,
        payload,
    )


@router.get("/{restaurant_id}/costing/dishes", response_model=DishCostingList)
def restaurant_dish_costings(
    restaurant_id: int,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    authorize_restaurant(db, current_user, restaurant_id, Permission.COSTING_READ)
    return list_dish_costings(db, restaurant_id)


@router.get("/by-slug/{slug}", response_model=RestaurantRead)
def restaurant_by_slug(
    slug: str,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    restaurant = get_restaurant_by_slug(db, slug)
    if restaurant is None:
        raise AppError(
            "Restaurante no encontrado.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="restaurant_not_found",
        )
    authorize_restaurant(db, current_user, restaurant.id, Permission.RESTAURANT_READ)
    return restaurant


@router.post("", response_model=RestaurantRead)
def restaurant_create(
    payload: RestaurantCreate,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    return create_restaurant_with_owner(db, current_user, payload)


@router.patch("/{restaurant_id}", response_model=RestaurantRead)
def restaurant_update(
    restaurant_id: int,
    payload: RestaurantUpdate,
    current_user: Annotated[User, Depends(require_current_user)],
    db: Session = Depends(get_db),
):
    authorize_restaurant(db, current_user, restaurant_id, Permission.RESTAURANT_MANAGE)
    return update_restaurant(db, restaurant_id, payload)
