from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.restaurant import RestaurantRead
from app.services.restaurant_service import list_restaurants


router = APIRouter(prefix="/restaurants", tags=["Restaurants"])


@router.get("", response_model=list[RestaurantRead])
def restaurants_index(db: Session = Depends(get_db)):
    return list_restaurants(db)
