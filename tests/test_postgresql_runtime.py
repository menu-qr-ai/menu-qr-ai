import os
import subprocess
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.exceptions import AppError
from app.database import Base
from app.models import (
    AnalyticsEvent,
    Category,
    Dish,
    DishIngredient,
    InventoryItem,
    InventoryMovement,
    KitchenTicket,
    KitchenTicketLine,
    Order,
    OrderFulfillment,
    OrderLine,
    Payment,
    Restaurant,
    RestaurantMembership,
    RestaurantTable,
    ServiceSession,
    ServiceSessionSettlement,
    User,
    Zone,
)
from app.schemas.payment import PaymentCreate
from app.services.order_fulfillment_service import fulfill_order
from app.services.payment_service import create_payment
from app.services.service_session_settlement_service import (
    settle_service_session,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
POSTGRES_URL = os.getenv("HOSTAI_TEST_POSTGRES_URL")
EXPECTED_HEAD = "0022_add_customer_qr_ordering_foundation"


@unittest.skipUnless(
    POSTGRES_URL,
    "HOSTAI_TEST_POSTGRES_URL is not configured",
)
class PostgreSQLRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert POSTGRES_URL is not None
        parsed = make_url(POSTGRES_URL)
        database_name = parsed.database or ""
        if not (
            database_name.startswith("hostai_")
            and database_name.endswith("_test")
        ):
            raise RuntimeError(
                "PostgreSQL runtime tests require a dedicated database "
                "named hostai_*_test"
            )
        cls.database_url = POSTGRES_URL
        cls.engine = create_engine(
            cls.database_url,
            pool_pre_ping=True,
        )
        cls.SessionTesting = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=cls.engine,
        )

    @classmethod
    def tearDownClass(cls):
        cls._reset_public_schema()
        cls.engine.dispose()

    def setUp(self):
        self._reset_public_schema()

    @classmethod
    def _reset_public_schema(cls):
        with cls.engine.begin() as connection:
            connection.exec_driver_sql("DROP SCHEMA IF EXISTS public CASCADE")
            connection.exec_driver_sql("CREATE SCHEMA public")

    def _run_alembic(self, *arguments: str):
        environment = os.environ.copy()
        environment["DATABASE_URL"] = self.database_url
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *arguments],
            cwd=PROJECT_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=180,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )

    def _upgrade_head(self):
        self._run_alembic("upgrade", "head")

    def test_all_revisions_upgrade_incrementally_on_postgresql(self):
        config = Config(str(PROJECT_ROOT / "alembic.ini"))
        script = ScriptDirectory.from_config(config)
        revisions = list(reversed(list(script.walk_revisions())))

        for revision in revisions:
            with self.subTest(revision=revision.revision):
                self._run_alembic("upgrade", revision.revision)
                with self.engine.connect() as connection:
                    current = connection.scalar(
                        text(
                            "SELECT version_num FROM alembic_version"
                        )
                    )
                self.assertEqual(current, revision.revision)

        with self.engine.connect() as connection:
            inspector = inspect(connection)
            table_names = set(inspector.get_table_names())
            payment_uniques = {
                tuple(item["column_names"])
                for item in inspector.get_unique_constraints("payments")
            }
            open_session_indexes = {
                item["name"]: item
                for item in inspector.get_indexes("service_sessions")
            }

        self.assertEqual(
            table_names,
            set(Base.metadata.tables) | {"alembic_version"},
        )
        self.assertIn(
            ("restaurant_id", "idempotency_key"),
            payment_uniques,
        )
        self.assertTrue(
            open_session_indexes[
                "uq_service_sessions_open_table"
            ]["unique"]
        )

    def test_recent_downgrade_and_upgrade_round_trip(self):
        self._upgrade_head()
        self._run_alembic(
            "downgrade",
            "0018_add_monetary_model_foundation",
        )
        with self.engine.connect() as connection:
            tables = set(inspect(connection).get_table_names())
            revision = connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )

        self.assertEqual(
            revision,
            "0018_add_monetary_model_foundation",
        )
        self.assertNotIn("order_fulfillments", tables)
        self.assertNotIn("service_session_settlements", tables)
        self.assertNotIn("payments", tables)

        self._upgrade_head()
        with self.engine.connect() as connection:
            revision = connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )
        self.assertEqual(revision, EXPECTED_HEAD)

    def test_fulfillment_settlement_and_payment_concurrency(self):
        self._upgrade_head()
        order_id, service_session_id, inventory_id = (
            self._seed_served_order()
        )

        fulfillment_results = self._race(
            lambda db, actor: fulfill_order(
                db,
                actor,
                1,
                order_id,
            )
        )
        self.assertEqual(
            sum(result[0] == "ok" for result in fulfillment_results),
            2,
        )

        with self.SessionTesting() as db:
            self.assertEqual(
                db.scalar(
                    select(func.count()).select_from(OrderFulfillment)
                ),
                1,
            )
            self.assertEqual(
                db.scalar(
                    select(func.count())
                    .select_from(InventoryMovement)
                    .where(InventoryMovement.movement_type == "OUT")
                ),
                1,
            )
            self.assertEqual(
                db.scalar(
                    select(func.count())
                    .select_from(AnalyticsEvent)
                    .where(
                        AnalyticsEvent.event_type
                        == "sale_processed"
                    )
                ),
                1,
            )
            self.assertEqual(
                db.get(InventoryItem, inventory_id).current_stock,
                98,
            )

        settlement_results = self._race(
            lambda db, actor: settle_service_session(
                db,
                actor,
                1,
                service_session_id,
            )
        )
        self.assertEqual(
            sum(result[0] == "ok" for result in settlement_results),
            2,
        )
        self.assertEqual(
            sum(
                result[1].is_idempotent_replay
                for result in settlement_results
            ),
            1,
        )

        with self.SessionTesting() as db:
            settlement = db.scalar(
                select(ServiceSessionSettlement)
            )
            settlement_id = settlement.id
            self.assertEqual(
                db.scalar(
                    select(func.count()).select_from(
                        ServiceSessionSettlement
                    )
                ),
                1,
            )
            self.assertEqual(
                db.get(
                    ServiceSession,
                    service_session_id,
                ).status,
                "closed",
            )

        payment_results = self._race(
            lambda db, actor: create_payment(
                db,
                actor,
                1,
                settlement_id,
                PaymentCreate(
                    amount=Decimal("8.00"),
                    method="card",
                    idempotency_key=(
                        f"postgres-race-{threading.get_ident()}"
                    ),
                ),
            )
        )
        self.assertEqual(
            sum(result[0] == "ok" for result in payment_results),
            1,
        )
        self.assertEqual(
            {
                result[1]
                for result in payment_results
                if result[0] == "error"
            },
            {"payment_amount_exceeds_remaining"},
        )

        with self.SessionTesting() as db:
            self.assertEqual(
                db.scalar(
                    select(func.count()).select_from(Payment)
                ),
                1,
            )
            self.assertEqual(
                db.scalar(select(func.sum(Payment.amount))),
                Decimal("8.00"),
            )

    def _race(self, action):
        barrier = threading.Barrier(2)

        def execute():
            with self.SessionTesting() as db:
                actor = db.get(User, 1)
                barrier.wait(timeout=10)
                try:
                    return "ok", action(db, actor)
                except AppError as exc:
                    return "error", exc.code

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(execute) for _ in range(2)]
            return [future.result(timeout=60) for future in futures]

    def _seed_served_order(self):
        now = datetime.utcnow()
        with self.SessionTesting() as db:
            restaurant = Restaurant(
                id=1,
                name="PostgreSQL Runtime",
                slug="postgresql-runtime",
                currency="EUR",
            )
            user = User(
                id=1,
                email="postgres-runtime@hostai.test",
                hashed_password="not-used",
                full_name="PostgreSQL Owner",
                role="owner",
                restaurant_id=1,
                is_active=True,
                created_at=now,
            )
            db.add_all([restaurant, user])
            db.flush()
            db.add(
                RestaurantMembership(
                    user_id=1,
                    restaurant_id=1,
                    role="owner",
                    is_active=True,
                    created_by_user_id=1,
                    created_at=now,
                )
            )
            category = Category(
                restaurant_id=1,
                name="Runtime menu",
            )
            zone = Zone(
                restaurant_id=1,
                name="Runtime zone",
            )
            inventory = InventoryItem(
                restaurant_id=1,
                name="Runtime ingredient",
                unit="unit",
                current_stock=100,
                minimum_stock=0,
                ideal_stock=100,
                cost=Decimal("3.00"),
            )
            db.add_all([category, zone, inventory])
            db.flush()
            dish = Dish(
                restaurant_id=1,
                category_id=category.id,
                name="Runtime dish",
                price=Decimal("12.34"),
            )
            table = RestaurantTable(
                restaurant_id=1,
                zone_id=zone.id,
                code="PG-1",
                capacity=4,
            )
            db.add_all([dish, table])
            db.flush()
            db.add(
                DishIngredient(
                    restaurant_id=1,
                    dish_id=dish.id,
                    inventory_item_id=inventory.id,
                    quantity=2,
                    unit="unit",
                )
            )
            service_session = ServiceSession(
                restaurant_id=1,
                table_id=table.id,
                status="open",
                opened_at=now,
                guest_count=2,
                opened_by_user_id=1,
                created_at=now,
                updated_at=now,
            )
            db.add(service_session)
            db.flush()
            order = Order(
                restaurant_id=1,
                service_session_id=service_session.id,
                status="submitted",
                created_by_user_id=1,
                submitted_at=now,
                created_at=now,
                updated_at=now,
            )
            db.add(order)
            db.flush()
            order_line = OrderLine(
                restaurant_id=1,
                order_id=order.id,
                dish_id=dish.id,
                dish_name=dish.name,
                quantity=1,
                unit_price=Decimal("12.34"),
                created_at=now,
                updated_at=now,
            )
            db.add(order_line)
            db.flush()
            ticket = KitchenTicket(
                restaurant_id=1,
                order_id=order.id,
                service_session_id=service_session.id,
                table_id=table.id,
                status="served",
                created_by_user_id=1,
                started_at=now,
                ready_at=now,
                served_at=now,
                created_at=now,
                updated_at=now,
            )
            db.add(ticket)
            db.flush()
            db.add(
                KitchenTicketLine(
                    restaurant_id=1,
                    kitchen_ticket_id=ticket.id,
                    order_line_id=order_line.id,
                    dish_id=dish.id,
                    dish_name=dish.name,
                    quantity=1,
                    status="served",
                    started_at=now,
                    ready_at=now,
                    served_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
            db.commit()
            return order.id, service_session.id, inventory.id
