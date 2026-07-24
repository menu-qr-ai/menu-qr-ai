import tempfile
import unittest
import re

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable
from sqlalchemy.orm import sessionmaker

from app.core.access import Permission, RestaurantRole, role_has_permission
from app.core.security import hash_password, verify_password
from app.database import Base, get_db
from app.main import app
from app.models import Restaurant, RestaurantMembership, User


TEST_PASSWORD = "Safe-test-password-2026"


class AccessControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.engine = create_engine(
            f"sqlite:///{cls.temp_dir.name}/access.db",
            connect_args={"check_same_thread": False},
        )
        cls.SessionTesting = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)
        Base.metadata.create_all(bind=cls.engine)
        cls._seed_database()

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
    def _seed_database(cls):
        with cls.SessionTesting() as db:
            restaurants = [
                Restaurant(id=1, name="Centro", slug="centro"),
                Restaurant(id=2, name="Playa", slug="playa"),
                Restaurant(id=3, name="Norte", slug="norte"),
            ]
            users = [
                User(
                    id=index,
                    email=f"{role}@hostai.test",
                    hashed_password=hash_password(TEST_PASSWORD),
                    full_name=role.title(),
                    role=role,
                    restaurant_id=1 if role != "outsider" else None,
                    is_active=True,
                )
                for index, role in enumerate(
                    ("owner", "manager", "waiter", "cook", "viewer", "outsider", "inactive"),
                    start=1,
                )
            ]
            other_owner = User(
                id=8,
                email="norte-owner@hostai.test",
                hashed_password=hash_password(TEST_PASSWORD),
                full_name="Norte Owner",
                role="owner",
                restaurant_id=3,
                is_active=True,
            )
            memberships = [
                RestaurantMembership(
                    id=1,
                    user_id=1,
                    restaurant_id=1,
                    role="owner",
                    is_active=True,
                    created_by_user_id=1,
                ),
                RestaurantMembership(
                    id=2,
                    user_id=1,
                    restaurant_id=2,
                    role="manager",
                    is_active=True,
                    created_by_user_id=1,
                ),
                RestaurantMembership(
                    id=3,
                    user_id=2,
                    restaurant_id=1,
                    role="manager",
                    is_active=True,
                    created_by_user_id=1,
                ),
                RestaurantMembership(
                    id=4,
                    user_id=3,
                    restaurant_id=1,
                    role="waiter",
                    is_active=True,
                    created_by_user_id=1,
                ),
                RestaurantMembership(
                    id=5,
                    user_id=4,
                    restaurant_id=1,
                    role="cook",
                    is_active=True,
                    created_by_user_id=1,
                ),
                RestaurantMembership(
                    id=6,
                    user_id=5,
                    restaurant_id=1,
                    role="viewer",
                    is_active=True,
                    created_by_user_id=1,
                ),
                RestaurantMembership(
                    id=7,
                    user_id=7,
                    restaurant_id=1,
                    role="viewer",
                    is_active=False,
                    created_by_user_id=1,
                ),
                RestaurantMembership(
                    id=8,
                    user_id=8,
                    restaurant_id=3,
                    role="owner",
                    is_active=True,
                    created_by_user_id=8,
                ),
            ]
            db.add_all([*restaurants, *users, other_owner, *memberships])
            db.commit()

    def _login(self, client: TestClient, email: str):
        response = client.post(
            "/api/auth/login",
            json={"email": email, "password": TEST_PASSWORD},
        )
        if response.status_code == 200:
            client.headers["X-CSRF-Token"] = response.json()[
                "csrf_token"
            ]
        return response

    def setUp(self):
        expected = {
            1: ("owner", True),
            2: ("manager", True),
            3: ("manager", True),
            4: ("waiter", True),
            5: ("cook", True),
            6: ("viewer", True),
            7: ("viewer", False),
            8: ("owner", True),
        }
        with self.SessionTesting() as db:
            db.execute(delete(RestaurantMembership).where(RestaurantMembership.id > 8))
            for membership_id, (role, is_active) in expected.items():
                membership = db.get(RestaurantMembership, membership_id)
                membership.role = role
                membership.is_active = is_active
            db.commit()

    def test_password_hash_is_salted_and_verifiable(self):
        first = hash_password(TEST_PASSWORD)
        second = hash_password(TEST_PASSWORD)

        self.assertNotEqual(first, second)
        self.assertTrue(verify_password(TEST_PASSWORD, first))
        self.assertFalse(verify_password("wrong", first))

    def test_unauthenticated_internal_endpoint_is_rejected(self):
        with TestClient(app) as client:
            response = client.get("/api/access/restaurants")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "authentication_required")

    def test_unauthenticated_workspace_redirects_to_login(self):
        with TestClient(app) as client:
            response = client.get("/admin/dashboard", follow_redirects=False)

        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["location"].startswith("/login"))

    def test_login_session_and_logout(self):
        with TestClient(app) as client:
            login = self._login(client, "owner@hostai.test")
            me = client.get("/api/auth/me")
            logout = client.post("/api/auth/logout")
            logged_out = client.get("/api/auth/me")

        self.assertEqual(login.status_code, 200)
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["user"]["email"], "owner@hostai.test")
        self.assertEqual(logout.status_code, 204)
        self.assertEqual(logged_out.status_code, 401)

    def test_single_restaurant_is_selected_automatically(self):
        with TestClient(app) as client:
            login = self._login(client, "manager@hostai.test")
            context = client.get("/api/access/context")

        self.assertEqual(login.json()["next_url"], "/admin/dashboard")
        self.assertEqual(context.status_code, 200)
        self.assertEqual(context.json()["active_restaurant"]["id"], 1)
        self.assertEqual(context.json()["membership"]["role"], "manager")

    def test_multi_restaurant_requires_selection_then_persists_context(self):
        with TestClient(app) as client:
            login = self._login(client, "owner@hostai.test")
            initial = client.get("/api/access/context")
            selected = client.put(
                "/api/access/active-restaurant",
                json={"restaurant_id": 2},
            )
            persisted = client.get("/api/access/context")
            default_dashboard = client.get("/api/dashboard/summary")

        self.assertEqual(login.json()["next_url"], "/app/restaurants")
        self.assertIsNone(initial.json()["active_restaurant"])
        self.assertEqual(selected.json()["active_restaurant"]["id"], 2)
        self.assertEqual(selected.json()["membership"]["role"], "manager")
        self.assertEqual(persisted.json()["active_restaurant"]["id"], 2)
        self.assertEqual(default_dashboard.status_code, 200)
        self.assertEqual(default_dashboard.json()["restaurant_id"], 2)

    def test_restaurant_switch_changes_active_context(self):
        with TestClient(app) as client:
            self._login(client, "owner@hostai.test")
            first = client.put(
                "/api/access/active-restaurant",
                json={"restaurant_id": 1},
            )
            second = client.put(
                "/api/access/active-restaurant",
                json={"restaurant_id": 2},
            )

        self.assertEqual(first.json()["active_restaurant"]["id"], 1)
        self.assertEqual(second.json()["active_restaurant"]["id"], 2)

    def test_invalid_restaurant_selection_is_rejected(self):
        with TestClient(app) as client:
            self._login(client, "owner@hostai.test")
            response = client.put(
                "/api/access/active-restaurant",
                json={"restaurant_id": 3},
            )
            context = client.get("/api/access/context")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "restaurant_access_denied")
        self.assertIsNone(context.json()["active_restaurant"])

    def test_active_context_never_replaces_membership_authorization(self):
        with TestClient(app) as client:
            self._login(client, "owner@hostai.test")
            client.put(
                "/api/access/active-restaurant",
                json={"restaurant_id": 1},
            )
            response = client.get("/api/restaurants/3")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "restaurant_access_denied")

    def test_revoked_active_membership_is_not_reused(self):
        with TestClient(app) as client:
            self._login(client, "manager@hostai.test")
            selected = client.get("/api/access/context")
            with self.SessionTesting() as db:
                db.get(RestaurantMembership, 3).is_active = False
                db.commit()
            revoked = client.get("/api/access/context")
            protected = client.get("/api/restaurants/1")

        self.assertEqual(selected.json()["active_restaurant"]["id"], 1)
        self.assertIsNone(revoked.json()["active_restaurant"])
        self.assertEqual(revoked.json()["available_restaurants"], [])
        self.assertEqual(protected.status_code, 403)

    def test_role_based_web_entry_points_are_mobile_ready(self):
        expectations = (
            ("waiter@hostai.test", "/staff/waiter"),
            ("cook@hostai.test", "/staff/kitchen"),
            ("viewer@hostai.test", "/admin/dashboard"),
        )
        for email, destination in expectations:
            with self.subTest(email=email), TestClient(app) as client:
                login = client.post(
                    "/login",
                    data={"email": email, "password": TEST_PASSWORD},
                    follow_redirects=False,
                )
                self.assertEqual(login.status_code, 303)
                self.assertEqual(login.headers["location"], destination)
                page = client.get(destination)
                self.assertEqual(page.status_code, 200)
                self.assertIn('name="viewport"', page.text)

    def test_web_multi_restaurant_selector_supports_touch_flow(self):
        with TestClient(app) as client:
            login = client.post(
                "/login",
                data={"email": "owner@hostai.test", "password": TEST_PASSWORD},
                follow_redirects=False,
            )
            selector = client.get(login.headers["location"])
            csrf_token = re.search(
                r'name="csrf_token" value="([^"]+)"',
                selector.text,
            ).group(1)
            switch = client.post(
                "/app/restaurants/select",
                data={
                    "restaurant_id": 2,
                    "csrf_token": csrf_token,
                },
                follow_redirects=False,
            )

        self.assertEqual(login.headers["location"], "/app/restaurants")
        self.assertEqual(selector.status_code, 200)
        self.assertIn("location-grid", selector.text)
        self.assertIn("Centro", selector.text)
        self.assertIn("Playa", selector.text)
        self.assertEqual(switch.status_code, 303)
        self.assertEqual(switch.headers["location"], "/admin/dashboard")

    def test_user_with_multiple_restaurants_sees_only_memberships(self):
        with TestClient(app) as client:
            self._login(client, "owner@hostai.test")
            response = client.get("/api/access/restaurants")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {
                (entry["restaurant"]["id"], entry["membership"]["role"])
                for entry in response.json()
            },
            {(1, "owner"), (2, "manager")},
        )

    def test_idor_to_unassigned_restaurant_is_rejected(self):
        with TestClient(app) as client:
            self._login(client, "owner@hostai.test")
            response = client.get("/api/restaurants/3")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "restaurant_access_denied")

    def test_inactive_membership_does_not_grant_access(self):
        with TestClient(app) as client:
            self._login(client, "inactive@hostai.test")
            listed = client.get("/api/access/restaurants")
            detail = client.get("/api/restaurants/1")

        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json(), [])
        self.assertEqual(detail.status_code, 403)

    def test_only_owner_can_manage_memberships(self):
        with TestClient(app) as owner_client:
            self._login(owner_client, "owner@hostai.test")
            created = owner_client.post(
                "/api/access/restaurants/1/memberships",
                json={"user_id": 6, "role": "viewer"},
            )

        with TestClient(app) as manager_client:
            self._login(manager_client, "manager@hostai.test")
            denied = manager_client.post(
                "/api/access/restaurants/1/memberships",
                json={"user_id": 6, "role": "waiter"},
            )

        self.assertEqual(created.status_code, 200)
        self.assertEqual(created.json()["role"], "viewer")
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.json()["error"]["code"], "permission_denied")

    def test_membership_can_be_deactivated_without_deleting_history(self):
        with TestClient(app) as owner_client:
            self._login(owner_client, "owner@hostai.test")
            deactivated = owner_client.patch(
                "/api/access/restaurants/1/memberships/3",
                json={"is_active": False},
            )

        with TestClient(app) as manager_client:
            self._login(manager_client, "manager@hostai.test")
            listed = manager_client.get("/api/access/restaurants")

        with self.SessionTesting() as db:
            stored = db.get(RestaurantMembership, 3)

        self.assertEqual(deactivated.status_code, 200)
        self.assertFalse(deactivated.json()["is_active"])
        self.assertEqual(listed.json(), [])
        self.assertIsNotNone(stored)
        self.assertFalse(stored.is_active)

    def test_last_owner_cannot_be_deactivated(self):
        with TestClient(app) as client:
            self._login(client, "owner@hostai.test")
            response = client.patch(
                "/api/access/restaurants/1/memberships/1",
                json={"is_active": False},
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "last_owner_required")

    def test_role_permission_matrix_is_stable(self):
        expected = {
            RestaurantRole.OWNER: (Permission.MEMBERSHIP_MANAGE, True),
            RestaurantRole.MANAGER: (Permission.INVENTORY_WRITE, True),
            RestaurantRole.WAITER: (Permission.OPERATIONS_WRITE, True),
            RestaurantRole.COOK: (Permission.PRODUCTION_WRITE, True),
            RestaurantRole.VIEWER: (Permission.INVENTORY_WRITE, False),
        }
        for role, (permission, allowed) in expected.items():
            with self.subTest(role=role):
                self.assertEqual(role_has_permission(role.value, permission), allowed)

    def test_access_schema_compiles_for_postgresql(self):
        for table_name in ("users", "restaurant_memberships"):
            with self.subTest(table=table_name):
                statement = CreateTable(Base.metadata.tables[table_name]).compile(
                    dialect=postgresql.dialect(),
                )
                self.assertIn(f"CREATE TABLE {table_name}", str(statement))

    def test_role_access_is_enforced_on_existing_endpoints(self):
        expectations = (
            ("manager@hostai.test", "/api/inventory/items?restaurant_id=1", 200),
            ("waiter@hostai.test", "/api/inventory/items?restaurant_id=1", 403),
            ("cook@hostai.test", "/api/inventory/items?restaurant_id=1", 200),
            ("viewer@hostai.test", "/api/dashboard/summary?restaurant_id=1", 200),
        )
        for email, path, status_code in expectations:
            with self.subTest(email=email), TestClient(app) as client:
                self._login(client, email)
                response = client.get(path)
                self.assertEqual(response.status_code, status_code)
