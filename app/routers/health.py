from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.version import APP_NAME, BUILD, VERSION
from app.database import get_db
from app.models import AnalyticsEvent, Restaurant


router = APIRouter(tags=["Health"])


@router.get("/test")
def legacy_health_check():
    return {"ok": True}


@router.get("/health")
def health_check(
    response: Response,
    db: Session = Depends(get_db),
):
    database_status = "ok"
    analytics_count = 0
    restaurant_count = 0
    try:
        db.execute(text("select 1"))
        analytics_count = db.scalar(select(func.count()).select_from(AnalyticsEvent)) or 0
        restaurant_count = db.scalar(select(func.count()).select_from(Restaurant)) or 0
    except SQLAlchemyError:
        db.rollback()
        database_status = "error"
        response.status_code = 503

    return {
        "status": "ok" if database_status == "ok" else "degraded",
        "app": APP_NAME,
        "version": VERSION,
        "build": BUILD,
        "database": database_status,
        "analytics": {"events": analytics_count},
        "restaurants": {"count": restaurant_count},
    }
