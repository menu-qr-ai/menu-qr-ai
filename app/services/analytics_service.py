import logging

from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.models import UsageLog

logger = logging.getLogger("app.analytics")


def get_usage_summary(db: Session) -> dict:
    try:
        rows = db.execute(
            select(UsageLog.feature, func.coalesce(func.sum(UsageLog.units), 0)).group_by(UsageLog.feature)
        ).all()
    except OperationalError:
        db.rollback()
        logger.info("usage_log_table_missing")
        rows = []

    summary = {
        "menu_views": 0,
        "translations": 0,
        "image_generations": 0,
    }
    for feature, total in rows:
        summary[feature] = int(total or 0)
    return summary
