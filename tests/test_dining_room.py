import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.dependencies.access import get_active_restaurant_id
from app.dependencies.auth import get_current_user
from app.main import app
from app.models import (
    Restaurant,
    RestaurantMembership,
    RestaurantTable,
    ServiceSession,
    User,
    Zone,
)


class DiningRoomTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.engine = create_engine(
            f"sqlite:///{cls.temp_dir.name}/dining.db",
            connect_args={"check_same_thread": False},
        )
        cls.SessionTesting = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=cls.engine,
        )
        Base.metadata.create_all(bind=cls.engine)
        cls._seed_access()

        def override_get_db():
            db = cls.SessionTesting()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        cls.engine.dispose()
        cls.temp_dir.cleanup()

    @classmethod
    def _seed_access(cls):
        with cls.SessionTesting() as db:
            restaurants = [
                Restaurant(id=1, name="Centro", slug="dining-centro"),
                Restaurant(id=2, name="Playa", slug="dining-playa"),
            ]
            roles = ("owner", "manager", "waiter", "cook", "viewer", "owner")
            users = [
                User(
                    id=index,
                    email=f"dining-{index}@hostai.test",
                    hashed_password="not-used",
                    full_name=f"Dining {role.title()} {index}",
                    role=role,
                    restaurant_id=1 if index < 6 else 2,
                    is_active=True,
                    created_at=datetime.utcnow(),
                )
                for index, role in enumerate(roles, start=1)
            ]
            memberships = [
                RestaurantMembership(
                    user_id=index,
                    restaurant_id=1 if index < 6 else 2,
                    role=role,
                    is_active=True,
                    created_by_user_id=1 if index < 6 else 6,
                )
                for index, role in enumerate(roles, start=1)
            ]
            memberships.append(
                RestaurantMembership(
                    user_id=1,
                    restaurant_id=2,
                    role="owner",
                    is_active=True,
                    created_by_user_id=1,
                )
            )
            db.add_all([*restaurants, *users, *memberships])
            db.commit()

    def setUp(self):
        with self.SessionTesting() as db:
            db.execute(delete(ServiceSession))
            db.execute(delete(RestaurantTable))
            db.execute(delete(Zone))
            db.commit()

    @contextmanager
    def client_as(self, user_id: int, *, active_restaurant_id: int = 1):
        role_by_user = {
            1: "owner",
            2: "manager",
            3: "waiter",
            4: "cook",
            5: "viewer",
            6: "owner",
        }
        user = User(
            id=user_id,
            email=f"dining-{user_id}@hostai.test",
            hashed_password="not-used",
            full_name=f"Dining {role_by_user[user_id].title()}",
            role=role_by_user[user_id],
            restaurant_id=active_restaurant_id,
            is_active=True,
            created_at=datetime.utcnow(),
        )
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_active_restaurant_id] = (
            lambda: active_restaurant_id
        )
        try:
            with TestClient(app) as client:
                yield client
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_active_restaurant_id, None)

    def _create_zone(
        self,
        client: TestClient,
        name: str = "Interior",
        *,
        restaurant_id: int = 1,
        is_active: bool = True,
    ) -> dict:
        response = client.post(
            f"/api/dining/{restaurant_id}/zones",
            json={"name": name, "display_order": 1, "is_active": is_active},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def _create_table(
        self,
        client: TestClient,
        zone_id: int | None,
        code: str = "M1",
        *,
        restaurant_id: int = 1,
        is_active: bool = True,
    ) -> dict:
        response = client.post(
            f"/api/dining/{restaurant_id}/tables",
            json={
                "zone_id": zone_id,
                "code": code,
                "capacity": 4,
                "display_order": 1,
                "is_active": is_active,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_zone_name_is_unique_per_restaurant(self):
        with self.client_as(1) as client:
            created = self._create_zone(client, "Interior")
            duplicate = client.post(
                "/api/dining/1/zones",
                json={"name": " interior ", "display_order": 2},
            )
            same_name_other_tenant = self._create_zone(
                client,
                "Interior",
                restaurant_id=2,
            )

        self.assertEqual(created["restaurant_id"], 1)
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.json()["error"]["code"], "zone_name_conflict")
        self.assertEqual(same_name_other_tenant["restaurant_id"], 2)

    def test_table_validates_code_capacity_and_zone_tenant(self):
        with self.client_as(1) as client:
            zone = self._create_zone(client)
            other_zone = self._create_zone(
                client,
                "Terraza",
                restaurant_id=2,
            )
            table = self._create_table(client, zone["id"])
            duplicate = client.post(
                "/api/dining/1/tables",
                json={"zone_id": zone["id"], "code": "m1", "capacity": 2},
            )
            invalid_capacity = client.post(
                "/api/dining/1/tables",
                json={"zone_id": zone["id"], "code": "M2", "capacity": 0},
            )
            other_tenant_zone = client.post(
                "/api/dining/1/tables",
                json={
                    "zone_id": other_zone["id"],
                    "code": "M3",
                    "capacity": 2,
                },
            )

        self.assertEqual(table["code"], "M1")
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.json()["error"]["code"], "table_code_conflict")
        self.assertEqual(invalid_capacity.status_code, 422)
        self.assertEqual(other_tenant_zone.status_code, 404)
        self.assertEqual(
            other_tenant_zone.json()["error"]["code"],
            "zone_not_found",
        )

    def test_inactive_zone_and_table_block_new_sessions(self):
        with self.client_as(1) as client:
            inactive_zone = self._create_zone(
                client,
                "Cerrada",
                is_active=False,
            )
            active_table_rejected = client.post(
                "/api/dining/1/tables",
                json={
                    "zone_id": inactive_zone["id"],
                    "code": "C1",
                    "capacity": 2,
                    "is_active": True,
                },
            )
            inactive_table = self._create_table(
                client,
                inactive_zone["id"],
                "C2",
                is_active=False,
            )
            session_rejected = client.post(
                f"/api/dining/1/tables/{inactive_table['id']}/sessions",
                json={"guest_count": 2},
            )

        self.assertEqual(active_table_rejected.status_code, 409)
        self.assertEqual(active_table_rejected.json()["error"]["code"], "zone_inactive")
        self.assertEqual(session_rejected.status_code, 409)
        self.assertEqual(session_rejected.json()["error"]["code"], "table_inactive")

    def test_service_session_lifecycle_and_single_open_invariant(self):
        with self.client_as(1) as owner:
            zone = self._create_zone(owner)
            table = self._create_table(owner, zone["id"])

        with self.client_as(3) as waiter:
            opened = waiter.post(
                f"/api/dining/1/tables/{table['id']}/sessions",
                json={"guest_count": 3, "note": "Ventana"},
            )
            duplicate = waiter.post(
                f"/api/dining/1/tables/{table['id']}/sessions",
                json={"guest_count": 2},
            )
            closed = waiter.post(
                f"/api/dining/1/sessions/{opened.json()['id']}/close",
            )
            double_close = waiter.post(
                f"/api/dining/1/sessions/{opened.json()['id']}/close",
            )
            reopened = waiter.post(
                f"/api/dining/1/tables/{table['id']}/sessions",
                json={"guest_count": 2},
            )
            cancelled = waiter.post(
                f"/api/dining/1/sessions/{reopened.json()['id']}/cancel",
            )

        self.assertEqual(opened.status_code, 201)
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.json()["error"]["code"], "table_already_occupied")
        self.assertEqual(closed.json()["status"], "closed")
        self.assertIsNotNone(closed.json()["closed_at"])
        self.assertEqual(double_close.status_code, 409)
        self.assertEqual(double_close.json()["error"]["code"], "service_session_not_open")
        self.assertEqual(cancelled.json()["status"], "cancelled")

    def test_guest_count_must_be_positive(self):
        with self.client_as(1) as client:
            zone = self._create_zone(client)
            table = self._create_table(client, zone["id"])
            response = client.post(
                f"/api/dining/1/tables/{table['id']}/sessions",
                json={"guest_count": 0},
            )

        self.assertEqual(response.status_code, 422)

    def test_dining_room_state_derives_occupancy(self):
        with self.client_as(1) as owner:
            zone = self._create_zone(owner)
            first = self._create_table(owner, zone["id"], "M1")
            self._create_table(owner, zone["id"], "M2")

        with self.client_as(3) as waiter:
            waiter.post(
                f"/api/dining/1/tables/{first['id']}/sessions",
                json={"guest_count": 4},
            )
            room = waiter.get("/api/dining/1/room")

        self.assertEqual(room.status_code, 200)
        self.assertEqual(room.json()["free_tables"], 1)
        self.assertEqual(room.json()["occupied_tables"], 1)
        occupied = next(
            item for item in room.json()["tables"] if item["table"]["id"] == first["id"]
        )
        self.assertTrue(occupied["is_occupied"])
        self.assertEqual(occupied["current_session"]["guest_count"], 4)
        self.assertIn("Dining Waiter", occupied["responsible_user_name"])

    def test_child_ids_are_isolated_between_restaurants(self):
        with self.client_as(1) as owner:
            zone_one = self._create_zone(owner, "Centro", restaurant_id=1)
            zone_two = self._create_zone(owner, "Playa", restaurant_id=2)
            table_two = self._create_table(
                owner,
                zone_two["id"],
                "P1",
                restaurant_id=2,
            )
            wrong_zone = owner.patch(
                f"/api/dining/1/zones/{zone_two['id']}",
                json={"name": "Intrusion"},
            )
            wrong_table = owner.patch(
                f"/api/dining/1/tables/{table_two['id']}",
                json={"capacity": 8},
            )
            wrong_session = owner.post(
                f"/api/dining/1/tables/{table_two['id']}/sessions",
                json={"guest_count": 2},
            )

        self.assertNotEqual(zone_one["id"], zone_two["id"])
        self.assertEqual(wrong_zone.status_code, 404)
        self.assertEqual(wrong_table.status_code, 404)
        self.assertEqual(wrong_session.status_code, 404)

    def test_unauthorized_restaurant_is_rejected_before_child_lookup(self):
        with self.client_as(2) as manager:
            response = manager.get("/api/dining/2/room")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "restaurant_access_denied")

    def test_role_permissions_for_dining_room(self):
        with self.client_as(1) as owner:
            zone = self._create_zone(owner)
            table = self._create_table(owner, zone["id"])

        cases = (
            (1, "get", "/api/dining/1/room", None, 200),
            (2, "post", "/api/dining/1/zones", {"name": "Manager"}, 201),
            (3, "get", "/api/dining/1/room", None, 200),
            (3, "post", "/api/dining/1/zones", {"name": "Waiter"}, 403),
            (4, "get", "/api/dining/1/room", None, 403),
            (5, "get", "/api/dining/1/room", None, 200),
            (
                5,
                "post",
                f"/api/dining/1/tables/{table['id']}/sessions",
                {"guest_count": 2},
                403,
            ),
        )
        for user_id, method, path, payload, expected in cases:
            with self.subTest(user_id=user_id, path=path), self.client_as(user_id) as client:
                if payload is None:
                    response = getattr(client, method)(path)
                else:
                    response = getattr(client, method)(path, json=payload)
                self.assertEqual(response.status_code, expected, response.text)

    def test_open_session_database_index_compiles_for_both_dialects(self):
        tables = ("restaurant_zones", "restaurant_tables", "service_sessions")
        for table_name in tables:
            with self.subTest(dialect="postgresql", table=table_name):
                sql = str(
                    CreateTable(Base.metadata.tables[table_name]).compile(
                        dialect=postgresql.dialect(),
                    )
                )
                self.assertIn(f"CREATE TABLE {table_name}", sql)
        open_index = next(
            index
            for index in Base.metadata.tables["service_sessions"].indexes
            if index.name == "uq_service_sessions_open_table"
        )
        postgres_index_sql = str(
            CreateIndex(open_index).compile(dialect=postgresql.dialect())
        )
        sqlite_index_sql = str(
            CreateIndex(open_index).compile(dialect=self.engine.dialect)
        )
        self.assertIn("WHERE status = 'open'", postgres_index_sql)
        self.assertIn("WHERE status = 'open'", sqlite_index_sql)
