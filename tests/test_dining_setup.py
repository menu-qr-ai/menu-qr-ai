import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.dependencies.access import get_active_restaurant_id
from app.dependencies.auth import get_current_user
from app.main import app
from app.models import (
    CustomerSession,
    QRCode,
    Restaurant,
    RestaurantMembership,
    RestaurantTable,
    ServiceSession,
    User,
    Zone,
)
from app.services import dining_setup_service

ROLE_BY_USER = {1: "owner", 2: "manager", 3: "waiter", 4: "cook", 5: "viewer", 6: "owner"}


class DiningSetupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.engine = create_engine(
            f"sqlite:///{cls.temp_dir.name}/dining_setup.db",
            connect_args={"check_same_thread": False},
        )
        cls.SessionTesting = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)
        Base.metadata.create_all(bind=cls.engine)
        with cls.SessionTesting() as db:
            db.add_all(
                [
                    Restaurant(id=1, name="Centro", slug="dining-centro"),
                    Restaurant(id=2, name="Playa", slug="dining-playa"),
                ]
            )
            for user_id, role in ROLE_BY_USER.items():
                restaurant_id = 1 if user_id < 6 else 2
                db.add(
                    User(
                        id=user_id,
                        email=f"dining-{user_id}@hostai.test",
                        hashed_password="not-used",
                        role=role,
                        restaurant_id=restaurant_id,
                        is_active=True,
                    )
                )
                db.flush()
                db.add(
                    RestaurantMembership(
                        user_id=user_id,
                        restaurant_id=restaurant_id,
                        role=role,
                        is_active=True,
                        created_by_user_id=user_id,
                    )
                )
            db.commit()

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()
        cls.temp_dir.cleanup()

    def setUp(self):
        def override_get_db():
            db = self.SessionTesting()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        with self.SessionTesting() as db:
            for model in (CustomerSession, QRCode, ServiceSession, RestaurantTable, Zone):
                db.execute(delete(model))
            db.commit()
            self.zone_id = self._add(db, Zone(restaurant_id=1, name="Interior"))
            self.table_ids = {
                code: self._add(
                    db,
                    RestaurantTable(
                        restaurant_id=1,
                        zone_id=self.zone_id,
                        code=code,
                        capacity=4,
                        is_active=code != "M3",
                    ),
                )
                for code in ("M1", "M2", "M3")
            }
            self.foreign_table_id = self._add(db, RestaurantTable(restaurant_id=2, code="P1", capacity=2))
            db.commit()

    def tearDown(self):
        app.dependency_overrides.clear()

    @staticmethod
    def _add(db, instance) -> int:
        db.add(instance)
        db.flush()
        return instance.id

    @contextmanager
    def client_as(self, user_id: int):
        restaurant_id = 1 if user_id < 6 else 2
        user = User(
            id=user_id,
            email=f"dining-{user_id}@hostai.test",
            hashed_password="not-used",
            role=ROLE_BY_USER[user_id],
            restaurant_id=restaurant_id,
            is_active=True,
            created_at=datetime.utcnow(),
        )
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_active_restaurant_id] = lambda: restaurant_id
        with TestClient(app) as client:
            yield client

    def _issue_qr(self, client: TestClient, table_id: int) -> dict:
        response = client.post(f"/api/dining/1/tables/{table_id}/customer-qr", json={"rotate": False})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_setup_lists_everything_with_qr_and_session_status_but_no_tokens(self):
        with self.client_as(1) as owner:
            qr = self._issue_qr(owner, self.table_ids["M1"])
            with self.SessionTesting() as db:
                # A revoked QR (e.g. after a rotation) must not count as a usable one.
                db.add(
                    QRCode(
                        restaurant_id=1,
                        table_id=self.table_ids["M2"],
                        access_token="revoked-token-for-test",
                        target_url="http://testserver/menu/table/revoked-token-for-test",
                        status="revoked",
                        revoked_at=datetime.utcnow(),
                    )
                )
                db.add(
                    ServiceSession(
                        restaurant_id=1,
                        table_id=self.table_ids["M2"],
                        status="open",
                        opened_at=datetime.utcnow(),
                        opened_by_user_id=1,
                    )
                )
                db.commit()
            response = owner.get("/api/dining/1/setup")

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        tables = {table["code"]: table for table in payload["tables"]}
        self.assertEqual(set(tables), {"M1", "M2", "M3"})
        self.assertTrue(tables["M1"]["has_customer_qr"])
        self.assertFalse(tables["M2"]["has_customer_qr"])
        self.assertTrue(tables["M2"]["has_open_session"])
        self.assertFalse(tables["M3"]["is_active"])
        token = qr["target_url"].rsplit("/", 1)[-1]
        self.assertNotIn(token, response.text)

    def test_qr_reachability_depends_on_app_url_host(self):
        cases = {
            "http://127.0.0.1:8000": False,
            "http://localhost:8000": False,
            "https://carta.mirestaurante.es": True,
        }
        for app_url, expected in cases.items():
            with self.subTest(app_url=app_url), patch.object(
                dining_setup_service, "settings", SimpleNamespace(app_url=app_url)
            ):
                self.assertEqual(dining_setup_service.customer_qr_reachable_from_phones(), expected)

    def test_zone_with_active_tables_cannot_be_deactivated(self):
        with self.client_as(2) as manager:
            blocked = manager.patch(f"/api/dining/1/zones/{self.zone_id}", json={"is_active": False})
            for code in ("M1", "M2"):
                manager.patch(f"/api/dining/1/tables/{self.table_ids[code]}", json={"is_active": False})
            allowed = manager.patch(f"/api/dining/1/zones/{self.zone_id}", json={"is_active": False})

        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(blocked.json()["error"]["code"], "zone_has_active_tables")
        self.assertEqual(allowed.status_code, 200, allowed.text)
        self.assertFalse(allowed.json()["is_active"])

    def test_print_page_shows_only_active_tables_with_qr(self):
        with self.client_as(1) as owner:
            self._issue_qr(owner, self.table_ids["M1"])
            self._issue_qr(owner, self.table_ids["M2"])
            owner.patch(f"/api/dining/1/tables/{self.table_ids['M2']}", json={"is_active": False})
            sheet = owner.get("/admin/dining/qr-print")
            single = owner.get(f"/admin/dining/qr-print?table_id={self.table_ids['M1']}")

        self.assertEqual(sheet.status_code, 200)
        self.assertIn("Mesa M1", sheet.text)
        self.assertNotIn("Mesa M2", sheet.text)
        self.assertNotIn("Mesa M3", sheet.text)
        self.assertEqual(single.text.count('class="qr-card"'), 1)

    def test_management_pages_and_setup_are_for_owner_and_manager_only(self):
        for user_id in (1, 2):
            with self.subTest(role=ROLE_BY_USER[user_id]), self.client_as(user_id) as staff:
                self.assertEqual(staff.get("/admin/dining").status_code, 200)
                self.assertEqual(staff.get("/api/dining/1/setup").status_code, 200)
        for user_id in (3, 4, 5):
            with self.subTest(role=ROLE_BY_USER[user_id]), self.client_as(user_id) as staff:
                self.assertEqual(staff.get("/admin/dining").status_code, 403)
                self.assertEqual(staff.get("/admin/dining/qr-print").status_code, 403)
                self.assertEqual(staff.get("/api/dining/1/setup").status_code, 403)

    def test_setup_is_isolated_per_restaurant(self):
        with self.client_as(1) as owner:
            foreign_setup = owner.get("/api/dining/2/setup")
            foreign_qr = owner.post(f"/api/dining/1/tables/{self.foreign_table_id}/customer-qr", json={"rotate": False})

        self.assertEqual(foreign_setup.status_code, 403)
        self.assertEqual(foreign_qr.status_code, 404)

    def test_management_page_links_the_new_sections(self):
        with self.client_as(1) as owner:
            response = owner.get("/admin/dining")

        self.assertIn('id="diningAdminBootstrap"', response.text)
        self.assertIn('href="/admin/dining"', response.text)
        self.assertIn('href="/admin/menu"', response.text)


if __name__ == "__main__":
    unittest.main()
