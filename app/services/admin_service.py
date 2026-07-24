import logging

from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.version import APP_NAME, BUILD, VERSION
from app.models import Category, Dish, RestaurantMembership, Subscription, UsageLog

logger = logging.getLogger("app.admin")

ADMIN_SECTIONS = (
    "Dashboard",
    "Restaurantes",
    "Categorias",
    "Platos",
    "IA",
    "Usuarios",
    "Suscripciones",
    "Configuracion",
    "Analitica",
)


def _count(db: Session, model: type, restaurant_id: int) -> int:
    try:
        return (
            db.scalar(
                select(func.count())
                .select_from(model)
                .where(model.restaurant_id == restaurant_id)
            )
            or 0
        )
    except OperationalError:
        db.rollback()
        logger.info("admin_metric_table_missing model=%s", model.__name__)
        return 0


def get_admin_dashboard_data(db: Session, restaurant_id: int) -> dict:
    return {
        "sections": ADMIN_SECTIONS,
        "metrics": [
            {"label": "Restaurantes", "value": 1},
            {"label": "Categorias", "value": _count(db, Category, restaurant_id)},
            {"label": "Platos", "value": _count(db, Dish, restaurant_id)},
            {"label": "Usuarios", "value": _count(db, RestaurantMembership, restaurant_id)},
            {"label": "Suscripciones", "value": _count(db, Subscription, restaurant_id)},
            {"label": "Eventos", "value": _count(db, UsageLog, restaurant_id)},
        ],
        "system_status": [
            {"label": "API", "status": "Operativa"},
            {"label": "Base de datos", "status": "SQLite"},
            {"label": "IA", "status": "Configurada por entorno"},
        ],
        "app_version": {"name": APP_NAME, "version": VERSION, "build": BUILD},
    }
