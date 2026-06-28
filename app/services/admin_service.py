import logging

from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.models import Category, Dish, Restaurant, Subscription, UsageLog, User

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


def _count(db: Session, model: type) -> int:
    try:
        return db.scalar(select(func.count()).select_from(model)) or 0
    except OperationalError:
        db.rollback()
        logger.info("admin_metric_table_missing model=%s", model.__name__)
        return 0


def get_admin_dashboard_data(db: Session) -> dict:
    return {
        "sections": ADMIN_SECTIONS,
        "metrics": [
            {"label": "Restaurantes", "value": _count(db, Restaurant)},
            {"label": "Categorias", "value": _count(db, Category)},
            {"label": "Platos", "value": _count(db, Dish)},
            {"label": "Usuarios", "value": _count(db, User)},
            {"label": "Suscripciones", "value": _count(db, Subscription)},
            {"label": "Eventos", "value": _count(db, UsageLog)},
        ],
        "system_status": [
            {"label": "API", "status": "Operativa"},
            {"label": "Base de datos", "status": "SQLite"},
            {"label": "IA", "status": "Configurada por entorno"},
        ],
    }
