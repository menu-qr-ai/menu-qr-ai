import re
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from app.core.security import hash_password
from app.database import Base, get_db
from app.dependencies.access import get_active_restaurant_id
from app.dependencies.auth import get_current_user
from app.main import app
from app.models import Restaurant, RestaurantMembership, User
from app.services.auth_service import authenticate_user
from app.services.team_service import PASSWORD_ALPHABET, generate_temporary_password

PASSWORD = "Original-password-2026"
# user_id -> (restaurant_id, role). Restaurant 2 belongs to someone else.
SEED = {1: (1, "owner"), 2: (1, "manager"), 3: (1, "waiter"), 4: (2, "owner")}


class TeamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.engine = create_engine(
            f"sqlite:///{cls.temp_dir.name}/team.db",
            connect_args={"check_same_thread": False},
        )
        cls.SessionTesting = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)
        Base.metadata.create_all(bind=cls.engine)
        cls.password_hash = hash_password(PASSWORD)

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
            for model in (RestaurantMembership, User, Restaurant):
                db.execute(delete(model))
            db.add_all(
                [
                    Restaurant(id=1, name="Centro", slug="team-centro"),
                    Restaurant(id=2, name="Ajeno", slug="team-ajeno"),
                ]
            )
            for user_id, (restaurant_id, role) in SEED.items():
                db.add(
                    User(
                        id=user_id,
                        email=f"user{user_id}@hostai.test",
                        hashed_password=self.password_hash,
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

    def tearDown(self):
        app.dependency_overrides.clear()

    @contextmanager
    def client_as(self, user_id: int):
        restaurant_id, role = SEED.get(user_id, (1, "waiter"))
        user = User(
            id=user_id,
            email=f"user{user_id}@hostai.test",
            hashed_password="not-used",
            role=role,
            restaurant_id=restaurant_id,
            is_active=True,
            created_at=datetime.utcnow(),
        )
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_active_restaurant_id] = lambda: restaurant_id
        with TestClient(app) as client:
            yield client

    def _login_works(self, email: str, password: str) -> bool:
        with self.SessionTesting() as db:
            return authenticate_user(db, email, password) is not None

    # --- Adding people -----------------------------------------------------

    def test_owner_creates_account_with_one_time_temporary_password(self):
        with self.client_as(1) as owner:
            response = owner.post(
                "/api/restaurants/1/team",
                json={"email": "  Laura@Restaurante.COM ", "full_name": " Laura  Pérez ", "role": "waiter"},
            )

        self.assertEqual(response.status_code, 201, response.text)
        payload = response.json()
        self.assertTrue(payload["created_account"])
        self.assertEqual(payload["member"]["email"], "laura@restaurante.com")
        self.assertEqual(payload["member"]["full_name"], "Laura Pérez")
        self.assertEqual(payload["member"]["role"], "waiter")
        self.assertTrue(self._login_works("laura@restaurante.com", payload["temporary_password"]))
        with self.SessionTesting() as db:
            stored = db.scalar(select(User).where(User.email == "laura@restaurante.com"))
            self.assertNotIn(payload["temporary_password"], stored.hashed_password)
        with self.client_as(1) as owner:
            listing = owner.get("/api/restaurants/1/team")
        self.assertNotIn("temporary_password", listing.text)

    def test_existing_account_gets_access_but_keeps_its_password(self):
        # user4 owns another venue: adding them must never reset their credentials.
        with self.client_as(1) as owner:
            response = owner.post("/api/restaurants/1/team", json={"email": "user4@hostai.test", "role": "cook"})

        self.assertEqual(response.status_code, 201, response.text)
        payload = response.json()
        self.assertFalse(payload["created_account"])
        self.assertIsNone(payload["temporary_password"])
        self.assertFalse(payload["member"]["can_reset_password"])
        self.assertTrue(self._login_works("user4@hostai.test", PASSWORD))

    def test_adding_an_active_member_twice_is_rejected(self):
        with self.client_as(1) as owner:
            response = owner.post("/api/restaurants/1/team", json={"email": "USER3@hostai.test", "role": "owner"})

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "member_already_active")
        with self.SessionTesting() as db:
            membership = db.scalar(select(RestaurantMembership).where(RestaurantMembership.user_id == 3))
            self.assertEqual(membership.role, "waiter")

    def test_invalid_email_and_inactive_account_are_rejected(self):
        with self.SessionTesting() as db:
            db.get(User, 4).is_active = False
            db.commit()
        with self.client_as(1) as owner:
            invalid = owner.post("/api/restaurants/1/team", json={"email": "laura-at-restaurante", "role": "waiter"})
            inactive = owner.post("/api/restaurants/1/team", json={"email": "user4@hostai.test", "role": "waiter"})

        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(inactive.status_code, 409)
        self.assertEqual(inactive.json()["error"]["code"], "user_inactive")

    # --- Password resets ---------------------------------------------------

    def _membership_id(self, user_id: int, restaurant_id: int = 1) -> int:
        with self.SessionTesting() as db:
            return db.scalar(
                select(RestaurantMembership.id).where(
                    RestaurantMembership.user_id == user_id,
                    RestaurantMembership.restaurant_id == restaurant_id,
                )
            )

    def test_owner_resets_password_of_own_staff(self):
        with self.client_as(1) as owner:
            response = owner.post(f"/api/restaurants/1/team/{self._membership_id(3)}/reset-password")

        self.assertEqual(response.status_code, 200, response.text)
        new_password = response.json()["temporary_password"]
        self.assertTrue(self._login_works("user3@hostai.test", new_password))
        self.assertFalse(self._login_works("user3@hostai.test", PASSWORD))

    def test_owner_cannot_reset_someone_who_also_works_elsewhere_or_themselves(self):
        with self.client_as(1) as owner:
            owner.post("/api/restaurants/1/team", json={"email": "user4@hostai.test", "role": "waiter"})
            foreign_owner = owner.post(f"/api/restaurants/1/team/{self._membership_id(4)}/reset-password")
            myself = owner.post(f"/api/restaurants/1/team/{self._membership_id(1)}/reset-password")

        for response in (foreign_owner, myself):
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json()["error"]["code"], "password_reset_not_allowed")
        self.assertTrue(self._login_works("user4@hostai.test", PASSWORD))
        self.assertTrue(self._login_works("user1@hostai.test", PASSWORD))

    # --- Access control ----------------------------------------------------

    def test_only_owners_manage_the_team(self):
        for user_id in (2, 3):
            with self.subTest(user=user_id), self.client_as(user_id) as staff:
                self.assertEqual(staff.get("/api/restaurants/1/team").status_code, 403)
                self.assertEqual(
                    staff.post("/api/restaurants/1/team", json={"email": "x@hostai.test", "role": "owner"}).status_code,
                    403,
                )
                self.assertEqual(
                    staff.post(f"/api/restaurants/1/team/{self._membership_id(3)}/reset-password").status_code,
                    403,
                )
                self.assertEqual(staff.get("/admin/team").status_code, 403)

    def test_team_is_isolated_per_restaurant(self):
        with self.client_as(1) as owner:
            listing = owner.get("/api/restaurants/1/team").json()
            foreign_list = owner.get("/api/restaurants/2/team")
            foreign_reset = owner.post(f"/api/restaurants/1/team/{self._membership_id(4, 2)}/reset-password")

        self.assertEqual({member["email"] for member in listing}, {f"user{i}@hostai.test" for i in (1, 2, 3)})
        self.assertEqual(foreign_list.status_code, 403)
        self.assertEqual(foreign_reset.status_code, 404)

    def test_revoked_member_loses_access_immediately(self):
        with self.client_as(1) as owner:
            revoke = owner.patch(
                f"/api/access/restaurants/1/memberships/{self._membership_id(3)}",
                json={"is_active": False},
            )
        self.assertEqual(revoke.status_code, 200, revoke.text)
        with self.client_as(3) as waiter:
            self.assertEqual(waiter.get("/api/dining/1/room").status_code, 403)

    def test_team_page_renders_for_owner_with_nav_entry(self):
        with self.client_as(1) as owner:
            response = owner.get("/admin/team")

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="teamAdminBootstrap"', response.text)
        self.assertIn('href="/admin/team"', response.text)
        self.assertIn('href="/app/password"', response.text)

    # --- Own password ------------------------------------------------------

    def test_user_changes_own_password(self):
        with self.client_as(3) as waiter:
            wrong = waiter.post("/api/auth/password", json={"current_password": "nope", "new_password": "Nueva-clave-2026"})
            same = waiter.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": PASSWORD})
            short = waiter.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": "corta"})
            ok = waiter.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": "Nueva-clave-2026"})

        self.assertEqual(wrong.status_code, 400)
        self.assertEqual(wrong.json()["error"]["code"], "current_password_invalid")
        self.assertEqual(same.status_code, 400)
        self.assertEqual(short.status_code, 422)
        self.assertEqual(ok.status_code, 204)
        self.assertTrue(self._login_works("user3@hostai.test", "Nueva-clave-2026"))
        self.assertFalse(self._login_works("user3@hostai.test", PASSWORD))

    def test_password_page_requires_login(self):
        with TestClient(app) as anonymous:
            response = anonymous.get("/app/password", follow_redirects=False)
        self.assertEqual(response.status_code, 303)

    def test_temporary_passwords_are_readable_and_random(self):
        passwords = {generate_temporary_password() for _ in range(50)}
        self.assertEqual(len(passwords), 50)
        for password in passwords:
            self.assertRegex(password, r"^[^-]{4}-[^-]{4}-[^-]{4}$")
            self.assertTrue(set(password.replace("-", "")) <= set(PASSWORD_ALPHABET))
            self.assertIsNone(re.search(r"[0O1lI]", password))


if __name__ == "__main__":
    unittest.main()
