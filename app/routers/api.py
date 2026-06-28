from fastapi import APIRouter

from app.core.config import settings
from app.services.subscription_service import get_available_plans


router = APIRouter(prefix="/api", tags=["API"])


@router.get("")
def api_root():
    return {
        "name": settings.app_name,
        "environment": settings.environment,
        "version": "0.3.0",
    }


@router.get("/plans")
def subscription_plans():
    return {"plans": get_available_plans()}
