import importlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

import app.models  # noqa: F401
from app.database import Base


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_HEAD = "0022_add_customer_qr_ordering_foundation"


class MigrationBaselineTests(unittest.TestCase):
    def _invoke_alembic(
        self,
        database_path: Path,
        *arguments: str,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["DATABASE_URL"] = f"sqlite:///{database_path.as_posix()}"
        return subprocess.run(
            [sys.executable, "-m", "alembic", *arguments],
            cwd=PROJECT_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=120,
        )

    def _run_alembic(self, database_path: Path, *arguments: str) -> None:
        result = self._invoke_alembic(database_path, *arguments)
        self.assertEqual(
            result.returncode,
            0,
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )

    def test_empty_sqlite_database_upgrades_to_head_without_seed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "fresh.db"
            self._run_alembic(database_path, "upgrade", "head")

            engine = create_engine(f"sqlite:///{database_path.as_posix()}")
            with engine.connect() as connection:
                table_names = set(inspect(connection).get_table_names())
                revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
                restaurant_count = connection.scalar(text("SELECT count(*) FROM restaurants"))
            engine.dispose()

        self.assertEqual(revision, EXPECTED_HEAD)
        self.assertEqual(restaurant_count, 0)
        self.assertEqual(
            table_names,
            set(Base.metadata.tables) | {"alembic_version"},
        )

    def test_supported_previous_revisions_upgrade_to_head(self):
        for revision in (
            "0013_add_inventory_movement_origin_type_index",
            "0014_add_restaurant_memberships",
            "0016_add_order_foundation",
            "0017_add_kitchen_ticket_foundation",
            "0018_add_monetary_model_foundation",
            "0019_add_order_fulfillment_bridge",
            "0020_add_service_session_settlement",
            "0021_add_payment_foundation",
        ):
            with self.subTest(revision=revision), tempfile.TemporaryDirectory() as temp_dir:
                database_path = Path(temp_dir) / "upgrade.db"
                self._run_alembic(database_path, "upgrade", revision)
                self._run_alembic(database_path, "upgrade", "head")
                engine = create_engine(f"sqlite:///{database_path.as_posix()}")
                with engine.connect() as connection:
                    current = connection.scalar(
                        text("SELECT version_num FROM alembic_version")
                    )
                engine.dispose()
                self.assertEqual(current, EXPECTED_HEAD)

    def test_fulfillment_revision_upgrades_and_round_trips_from_0018(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "fulfillment.db"
            self._run_alembic(
                database_path,
                "upgrade",
                "0018_add_monetary_model_foundation",
            )
            engine = create_engine(f"sqlite:///{database_path.as_posix()}")
            with engine.connect() as connection:
                tables_at_0018 = set(
                    inspect(connection).get_table_names()
                )
            engine.dispose()

            self._run_alembic(database_path, "upgrade", "head")
            engine = create_engine(f"sqlite:///{database_path.as_posix()}")
            with engine.connect() as connection:
                tables_at_head = set(
                    inspect(connection).get_table_names()
                )
                revision_at_head = connection.scalar(
                    text("SELECT version_num FROM alembic_version")
                )
            engine.dispose()

            self._run_alembic(
                database_path,
                "downgrade",
                "0018_add_monetary_model_foundation",
            )
            engine = create_engine(f"sqlite:///{database_path.as_posix()}")
            with engine.connect() as connection:
                tables_after_downgrade = set(
                    inspect(connection).get_table_names()
                )
            engine.dispose()
            self._run_alembic(database_path, "upgrade", "head")

        self.assertNotIn("order_fulfillments", tables_at_0018)
        self.assertIn("order_fulfillments", tables_at_head)
        self.assertIn("order_fulfillment_lines", tables_at_head)
        self.assertEqual(revision_at_head, EXPECTED_HEAD)
        self.assertNotIn(
            "order_fulfillments",
            tables_after_downgrade,
        )

    def test_settlement_revision_upgrades_and_round_trips_from_0019(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "settlement.db"
            self._run_alembic(
                database_path,
                "upgrade",
                "0019_add_order_fulfillment_bridge",
            )
            engine = create_engine(f"sqlite:///{database_path.as_posix()}")
            with engine.connect() as connection:
                tables_at_0019 = set(
                    inspect(connection).get_table_names()
                )
            engine.dispose()

            self._run_alembic(database_path, "upgrade", "head")
            engine = create_engine(f"sqlite:///{database_path.as_posix()}")
            with engine.connect() as connection:
                tables_at_head = set(
                    inspect(connection).get_table_names()
                )
                revision_at_head = connection.scalar(
                    text("SELECT version_num FROM alembic_version")
                )
            engine.dispose()

            self._run_alembic(
                database_path,
                "downgrade",
                "0019_add_order_fulfillment_bridge",
            )
            engine = create_engine(f"sqlite:///{database_path.as_posix()}")
            with engine.connect() as connection:
                tables_after_downgrade = set(
                    inspect(connection).get_table_names()
                )
            engine.dispose()
            self._run_alembic(database_path, "upgrade", "head")

        self.assertNotIn(
            "service_session_settlements",
            tables_at_0019,
        )
        self.assertIn(
            "service_session_settlements",
            tables_at_head,
        )
        self.assertIn(
            "service_session_settlement_orders",
            tables_at_head,
        )
        self.assertIn(
            "service_session_settlement_lines",
            tables_at_head,
        )
        self.assertEqual(revision_at_head, EXPECTED_HEAD)
        self.assertNotIn(
            "service_session_settlements",
            tables_after_downgrade,
        )

    def test_payment_revision_upgrades_and_round_trips_from_0020(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "payment.db"
            self._run_alembic(
                database_path,
                "upgrade",
                "0020_add_service_session_settlement",
            )
            engine = create_engine(f"sqlite:///{database_path.as_posix()}")
            with engine.connect() as connection:
                tables_at_0020 = set(
                    inspect(connection).get_table_names()
                )
            engine.dispose()

            self._run_alembic(database_path, "upgrade", "head")
            engine = create_engine(f"sqlite:///{database_path.as_posix()}")
            with engine.connect() as connection:
                inspector = inspect(connection)
                tables_at_head = set(inspector.get_table_names())
                revision_at_head = connection.scalar(
                    text("SELECT version_num FROM alembic_version")
                )
                payment_columns = {
                    column["name"]: column
                    for column in inspector.get_columns("payments")
                }
                payment_uniques = {
                    tuple(constraint["column_names"])
                    for constraint in inspector.get_unique_constraints(
                        "payments"
                    )
                }
            engine.dispose()

            self._run_alembic(
                database_path,
                "downgrade",
                "0020_add_service_session_settlement",
            )
            engine = create_engine(f"sqlite:///{database_path.as_posix()}")
            with engine.connect() as connection:
                tables_after_downgrade = set(
                    inspect(connection).get_table_names()
                )
            engine.dispose()
            self._run_alembic(database_path, "upgrade", "head")

        self.assertNotIn("payments", tables_at_0020)
        self.assertIn("payments", tables_at_head)
        self.assertEqual(
            str(payment_columns["amount"]["type"]),
            "NUMERIC(12, 2)",
        )
        self.assertIn(
            ("restaurant_id", "idempotency_key"),
            payment_uniques,
        )
        self.assertEqual(revision_at_head, EXPECTED_HEAD)
        self.assertNotIn("payments", tables_after_downgrade)

    def test_customer_revision_upgrades_and_round_trips_from_0021(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "customer.db"
            self._run_alembic(
                database_path,
                "upgrade",
                "0021_add_payment_foundation",
            )
            engine = create_engine(
                f"sqlite:///{database_path.as_posix()}"
            )
            with engine.connect() as connection:
                tables_at_0021 = set(
                    inspect(connection).get_table_names()
                )
            engine.dispose()

            self._run_alembic(database_path, "upgrade", "head")
            engine = create_engine(
                f"sqlite:///{database_path.as_posix()}"
            )
            with engine.connect() as connection:
                inspector = inspect(connection)
                tables_at_head = set(inspector.get_table_names())
                revision_at_head = connection.scalar(
                    text("SELECT version_num FROM alembic_version")
                )
                order_columns = {
                    column["name"]
                    for column in inspector.get_columns("orders")
                }
                qr_columns = {
                    column["name"]
                    for column in inspector.get_columns("qr_codes")
                }
                customer_indexes = {
                    index["name"]: index
                    for index in inspector.get_indexes(
                        "customer_sessions"
                    )
                }
            engine.dispose()

            self._run_alembic(
                database_path,
                "downgrade",
                "0021_add_payment_foundation",
            )
            engine = create_engine(
                f"sqlite:///{database_path.as_posix()}"
            )
            with engine.connect() as connection:
                inspector = inspect(connection)
                tables_after_downgrade = set(
                    inspector.get_table_names()
                )
                order_columns_after_downgrade = {
                    column["name"]
                    for column in inspector.get_columns("orders")
                }
            engine.dispose()
            self._run_alembic(database_path, "upgrade", "head")

        self.assertNotIn("customer_sessions", tables_at_0021)
        self.assertIn("customer_sessions", tables_at_head)
        self.assertIn("customer_session_id", order_columns)
        self.assertIn("access_token", qr_columns)
        self.assertTrue(
            customer_indexes[
                "uq_customer_sessions_active_service_session"
            ]["unique"]
        )
        self.assertEqual(revision_at_head, EXPECTED_HEAD)
        self.assertNotIn(
            "customer_sessions",
            tables_after_downgrade,
        )
        self.assertNotIn(
            "customer_session_id",
            order_columns_after_downgrade,
        )

    def test_existing_float_money_upgrades_and_round_trips_without_loss(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "existing.db"
            self._run_alembic(
                database_path,
                "upgrade",
                "0017_add_kitchen_ticket_foundation",
            )
            engine = create_engine(f"sqlite:///{database_path.as_posix()}")
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO restaurants (id, name, slug) "
                        "VALUES (1, 'Money', 'money')"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO categories (id, name, restaurant_id) "
                        "VALUES (1, 'Menu', 1)"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO dishes "
                        "(id, name, price, category_id, restaurant_id) "
                        "VALUES (1, 'Decimal', 10.95, 1, 1), "
                        "(2, 'Unpriced', NULL, 1, 1)"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO users "
                        "(id, email, hashed_password, restaurant_id) "
                        "VALUES (1, 'money@hostai.test', 'not-used', 1)"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO restaurant_zones "
                        "(id, restaurant_id, name) VALUES (1, 1, 'Main')"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO restaurant_tables "
                        "(id, restaurant_id, zone_id, code, capacity) "
                        "VALUES (1, 1, 1, 'M1', 4)"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO service_sessions "
                        "(id, restaurant_id, table_id, opened_by_user_id) "
                        "VALUES (1, 1, 1, 1)"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO orders "
                        "(id, restaurant_id, service_session_id, "
                        "created_by_user_id) VALUES (1, 1, 1, 1)"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO order_lines "
                        "(id, restaurant_id, order_id, dish_id, dish_name, "
                        "quantity, unit_price) "
                        "VALUES (1, 1, 1, 1, 'Decimal', 3, 0.10)"
                    )
                )
            engine.dispose()

            self._run_alembic(database_path, "upgrade", "head")
            engine = create_engine(f"sqlite:///{database_path.as_posix()}")
            with engine.connect() as connection:
                upgraded_prices = connection.execute(
                    text("SELECT price FROM dishes ORDER BY id")
                ).scalars().all()
                upgraded_snapshot = connection.scalar(
                    text("SELECT unit_price FROM order_lines WHERE id = 1")
                )
                upgraded_types = {
                    column["name"]: str(column["type"])
                    for column in inspect(connection).get_columns("dishes")
                }
            engine.dispose()

            self._run_alembic(
                database_path,
                "downgrade",
                "0017_add_kitchen_ticket_foundation",
            )
            self._run_alembic(database_path, "upgrade", "head")
            engine = create_engine(f"sqlite:///{database_path.as_posix()}")
            with engine.connect() as connection:
                revision = connection.scalar(
                    text("SELECT version_num FROM alembic_version")
                )
                round_trip_price = connection.scalar(
                    text("SELECT price FROM dishes WHERE id = 1")
                )
                round_trip_snapshot = connection.scalar(
                    text("SELECT unit_price FROM order_lines WHERE id = 1")
                )
            engine.dispose()

        self.assertEqual(upgraded_prices, [10.95, None])
        self.assertEqual(upgraded_snapshot, 0.1)
        self.assertEqual(upgraded_types["price"], "NUMERIC(12, 2)")
        self.assertEqual(revision, EXPECTED_HEAD)
        self.assertEqual(round_trip_price, 10.95)
        self.assertEqual(round_trip_snapshot, 0.1)

    def test_incompatible_existing_money_blocks_migration(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "invalid.db"
            self._run_alembic(
                database_path,
                "upgrade",
                "0017_add_kitchen_ticket_foundation",
            )
            engine = create_engine(f"sqlite:///{database_path.as_posix()}")
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO restaurants (id, name, slug) "
                        "VALUES (1, 'Invalid', 'invalid')"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO categories (id, name, restaurant_id) "
                        "VALUES (1, 'Menu', 1)"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO dishes "
                        "(id, name, price, category_id, restaurant_id) "
                        "VALUES (1, 'Invalid', 1.234, 1, 1)"
                    )
                )
            engine.dispose()

            result = self._invoke_alembic(database_path, "upgrade", "head")
            engine = create_engine(f"sqlite:///{database_path.as_posix()}")
            with engine.connect() as connection:
                revision = connection.scalar(
                    text("SELECT version_num FROM alembic_version")
                )
            engine.dispose()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Monetary migration blocked", result.stderr)
        self.assertIn("mas de dos decimales", result.stderr)
        self.assertEqual(
            revision,
            "0017_add_kitchen_ticket_foundation",
        )

    def test_recent_migration_history_is_preserved(self):
        config = Config(str(PROJECT_ROOT / "alembic.ini"))
        script = ScriptDirectory.from_config(config)
        revisions = {revision.revision for revision in script.walk_revisions()}

        self.assertTrue(
            {
                "0014_add_restaurant_memberships",
                "0015_add_dining_room_foundation",
                "0016_add_order_foundation",
                "0017_add_kitchen_ticket_foundation",
                "0018_add_monetary_model_foundation",
                "0019_add_order_fulfillment_bridge",
                "0020_add_service_session_settlement",
                "0021_add_payment_foundation",
                "0022_add_customer_qr_ordering_foundation",
            }.issubset(revisions)
        )
        self.assertEqual(script.get_current_head(), EXPECTED_HEAD)

    def test_complete_metadata_compiles_for_postgresql(self):
        compiled_tables = {}
        compiled_indexes = {}
        dialect = postgresql.dialect()
        for table_name, table in Base.metadata.tables.items():
            compiled_tables[table_name] = str(
                CreateTable(table).compile(dialect=dialect)
            )
            compiled_indexes[table_name] = [
                str(CreateIndex(index).compile(dialect=dialect))
                for index in table.indexes
            ]

        self.assertEqual(set(compiled_tables), set(Base.metadata.tables))
        self.assertIn("CREATE TABLE restaurants", compiled_tables["restaurants"])
        self.assertIn("CREATE TABLE restaurant_memberships", compiled_tables["restaurant_memberships"])
        self.assertIn("CREATE TABLE orders", compiled_tables["orders"])
        self.assertIn(
            "CREATE TABLE order_fulfillments",
            compiled_tables["order_fulfillments"],
        )
        self.assertIn(
            "CREATE TABLE order_fulfillment_lines",
            compiled_tables["order_fulfillment_lines"],
        )
        self.assertIn(
            "CREATE TABLE service_session_settlements",
            compiled_tables["service_session_settlements"],
        )
        self.assertIn(
            "NUMERIC(12, 2)",
            compiled_tables["service_session_settlements"],
        )
        self.assertIn(
            "CREATE TABLE payments",
            compiled_tables["payments"],
        )
        self.assertIn(
            "NUMERIC(12, 2)",
            compiled_tables["payments"],
        )
        self.assertIn(
            "CREATE TABLE customer_sessions",
            compiled_tables["customer_sessions"],
        )
        self.assertIn(
            "uq_customer_sessions_active_service_session",
            " ".join(compiled_indexes["customer_sessions"]),
        )
        self.assertIn(
            "uq_orders_active_customer_session",
            " ".join(compiled_indexes["orders"]),
        )
        self.assertIn(
            "UNIQUE (restaurant_id, idempotency_key)",
            compiled_tables["payments"],
        )
        self.assertIn("NUMERIC(12, 2)", compiled_tables["dishes"])
        self.assertIn("NUMERIC(12, 2)", compiled_tables["order_lines"])
        self.assertTrue(
            any(
                "WHERE status = 'open'" in statement
                for statement in compiled_indexes["service_sessions"]
            )
        )

    def test_postgresql_revision_column_supports_historical_identifiers(self):
        output = io.StringIO()
        context = MigrationContext.configure(
            dialect_name="postgresql",
            opts={"as_sql": True, "output_buffer": output},
        )
        migration = importlib.import_module(
            "migrations.versions.0003_extend_restaurants_for_multitenancy"
        )
        with patch.object(migration, "op", Operations(context)):
            migration._widen_alembic_revision_column()

        config = Config(str(PROJECT_ROOT / "alembic.ini"))
        script = ScriptDirectory.from_config(config)
        longest_revision = max(
            script.walk_revisions(),
            key=lambda item: len(item.revision),
        ).revision

        self.assertLessEqual(len(longest_revision), 255)
        self.assertIn(
            "ALTER TABLE alembic_version "
            "ALTER COLUMN version_num TYPE VARCHAR(255)",
            output.getvalue(),
        )

    def test_postgresql_monetary_alter_ddl_compiles(self):
        output = io.StringIO()
        context = MigrationContext.configure(
            dialect_name="postgresql",
            opts={"as_sql": True, "output_buffer": output},
        )
        migration = importlib.import_module(
            "migrations.versions.0018_add_monetary_model_foundation"
        )
        with patch.object(migration, "op", Operations(context)):
            migration._upgrade_column_types()

        ddl = output.getvalue()
        self.assertIn(
            "ALTER TABLE dishes ALTER COLUMN price "
            "TYPE NUMERIC(12, 2) USING ROUND(price::numeric, 2)",
            ddl,
        )
        self.assertIn(
            "ALTER TABLE order_lines ALTER COLUMN unit_price "
            "TYPE NUMERIC(12, 2) USING ROUND(unit_price::numeric, 2)",
            ddl,
        )

    def test_installation_documentation_keeps_migrations_and_seed_explicit(self):
        readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("python -m alembic upgrade head", readme)
        self.assertIn("SECRET_KEY", readme)
        self.assertIn("python -m app.utils.demo_seed", readme)
        self.assertIn("No se ejecuta automaticamente", readme)
