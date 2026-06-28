from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from starlette import status

from app.core.exceptions import AppError
from app.database import get_db
from app.schemas.restaurant import RestaurantCreate, RestaurantRead, RestaurantUpdate
from app.services.restaurant_service import (
    create_restaurant,
    get_restaurant_by_slug,
    list_restaurants,
    require_restaurant,
    update_restaurant,
)


router = APIRouter(prefix="/api/restaurants", tags=["Restaurants"])


@router.get("", response_model=list[RestaurantRead])
def restaurants_index(db: Session = Depends(get_db)):
    return list_restaurants(db)


@router.get("/{restaurant_id}", response_model=RestaurantRead)
def restaurant_detail(restaurant_id: int, db: Session = Depends(get_db)):
    return require_restaurant(db, restaurant_id)


@router.get("/by-slug/{slug}", response_model=RestaurantRead)
def restaurant_by_slug(slug: str, db: Session = Depends(get_db)):
    restaurant = get_restaurant_by_slug(db, slug)
    if restaurant is None:
        raise AppError(
            "Restaurante no encontrado.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="restaurant_not_found",
        )
    return restaurant


@router.post("", response_model=RestaurantRead)
def restaurant_create(payload: RestaurantCreate, db: Session = Depends(get_db)):
    return create_restaurant(db, payload)


@router.patch("/{restaurant_id}", response_model=RestaurantRead)
def restaurant_update(restaurant_id: int, payload: RestaurantUpdate, db: Session = Depends(get_db)):
    return update_restaurant(db, restaurant_id, payload)
