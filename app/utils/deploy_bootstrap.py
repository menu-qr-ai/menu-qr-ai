"""Runs at every start on Render (free plan has no pre-deploy hook or shell).

Loads the demo restaurant only when SEED_DEMO_ON_EMPTY=true and the database
has no restaurant yet, so restarts and redeploys never overwrite real data.
"""

import logging
import os

from sqlalchemy import func, select

from app.core.config import settings
from app.database import SessionLocal
from app.models import Restaurant
from app.utils.demo_seed import DEMO_OWNER_PASSWORD, seed_demo_database

logger = logging.getLogger("app.bootstrap")
MIN_DEMO_PASSWORD_LENGTH = 12


def demo_owner_password() -> str:
    password = os.getenv("DEMO_OWNER_PASSWORD", "").strip()
    if password:
        if len(password) < MIN_DEMO_PASSWORD_LENGTH:
            raise SystemExit(f"DEMO_OWNER_PASSWORD must have at least {MIN_DEMO_PASSWORD_LENGTH} characters.")
        return password
    if settings.is_production:
        # The default demo password is published in the README.
        raise SystemExit("DEMO_OWNER_PASSWORD is required to seed the demo in production.")
    return DEMO_OWNER_PASSWORD


def bootstrap() -> str:
    if os.getenv("SEED_DEMO_ON_EMPTY", "").strip().lower() not in {"1", "true", "yes"}:
        return "skipped: SEED_DEMO_ON_EMPTY is not enabled"
    with SessionLocal() as db:
        if db.scalar(select(func.count()).select_from(Restaurant)):
            return "skipped: database already has restaurants"
        result = seed_demo_database(db, owner_password=demo_owner_password())
    return f"demo seeded: restaurant_id={result['restaurant_id']} slug={result['slug']}"


def main() -> None:
    outcome = bootstrap()
    logger.warning("deploy_bootstrap %s", outcome)
    print(f"deploy_bootstrap {outcome}")


if __name__ == "__main__":
    main()
