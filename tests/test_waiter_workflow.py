import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.dependencies.access import get_active_restaurant_id
from app.dependencies.auth import get_current_user
from app.main import app
from app.models import (
    Category,
    Dish,
    Order,
    OrderLine,
    Restaurant,
    RestaurantMembership,
    RestaurantTable,
    ServiceSession,
    User,
    Zone,
)


class WaiterWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.engine = create_engine(
            f"sqlite:///{cls.temp_dir.name}/waiter.db",
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
                Restaurant(id=1, name="Centro", slug="waiter-centro"),
                Restaurant(id=2, name="Playa", slug="waiter-playa"),
            ]
            roles = ("owner", "manager", "waiter", "cook", "viewer")
            users = [
                User(
                    id=index,
                    email=f"waiter-ui-{index}@hostai.test",
                    hashed_password="not-used",
                    full_name=f"Waiter UI {role.title()}",
                    role=role,
                    restaurant_id=1,
                    is_active=True,
                    created_at=datetime.utcnow(),
                )
                for index, role in enumerate(roles, start=1)
            ]
            memberships = [
                RestaurantMembership(
                    user_id=index,
                    restaurant_id=1,
                    role=role,
                    is_active=True,
                    created_by_user_id=1,
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
            db.execute(delete(OrderLine))
            db.execute(delete(Order))
            db.execute(delete(ServiceSession))
            db.execute(delete(RestaurantTable))
            db.execute(delete(Zone))
            db.execute(delete(Dish))
            db.execute(delete(Category))
            for restaurant_id, label in ((1, "Centro"), (2, "Playa")):
                category = Category(
                    name=f"Carta {label}",
                    restaurant_id=restaurant_id,
                )
                zone = Zone(
                    restaurant_id=restaurant_id,
                    name=f"Sala {label}",
                )
                db.add_all([category, zone])
                db.flush()
                db.add_all(
                    [
                        Dish(
                            name=f"Arroz {label}",
                            description="Preparado al momento",
                            price=14.5,
                            ingredients="Arroz, caldo",
                            allergens="Apio",
                            category_id=category.id,
                            restaurant_id=restaurant_id,
                        ),
                        RestaurantTable(
                            restaurant_id=restaurant_id,
                            zone_id=zone.id,
                            code=f"{label[0]}01",
                            capacity=4,
                        ),
                    ]
                )
            db.commit()

    @contextmanager
    def client_as(self, user_id: int, *, active_restaurant_id: int = 1):
        roles = {
            1: "owner",
            2: "manager",
            3: "waiter",
            4: "cook",
            5: "viewer",
        }
        user = User(
            id=user_id,
            email=f"waiter-ui-{user_id}@hostai.test",
            hashed_password="not-used",
            full_name=f"Waiter UI {roles[user_id].title()}",
            role=roles[user_id],
            restaurant_id=1,
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

    def test_owner_manager_and_waiter_can_open_workspace(self):
        for user_id in (1, 2, 3):
            with self.subTest(user_id=user_id), self.client_as(user_id) as client:
                response = client.get("/staff/waiter")
                self.assertEqual(response.status_code, 200, response.text)
                self.assertIn("Operativa de sala", response.text)

    def test_legacy_waiter_entry_redirects_to_operational_workspace(self):
        with self.client_as(3) as waiter:
            response = waiter.get("/app/waiter", follow_redirects=False)

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/staff/waiter")

    def test_cook_and_viewer_cannot_open_operational_workspace(self):
        for user_id in (4, 5):
            with self.subTest(user_id=user_id), self.client_as(user_id) as client:
                response = client.get("/staff/waiter")
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json()["error"]["code"], "permission_denied")

    def test_workspace_lists_tables_active_context_and_current_menu(self):
        with self.client_as(3) as waiter:
            response = waiter.get("/staff/waiter")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Local activo", response.text)
        self.assertIn("Centro", response.text)
        self.assertIn("C01", response.text)
        self.assertIn("Arroz Centro", response.text)
        self.assertIn("Apio", response.text)
        self.assertIn("Cambiar local", response.text)

    def test_existing_session_is_rendered_with_operational_context(self):
        with self.SessionTesting() as db:
            table = db.query(RestaurantTable).filter_by(restaurant_id=1).one()
            service_session = ServiceSession(
                restaurant_id=1,
                table_id=table.id,
                status="open",
                opened_at=datetime.utcnow(),
                guest_count=3,
                opened_by_user_id=3,
            )
            db.add(service_session)
            db.commit()
            session_id = service_session.id

        with self.client_as(3) as waiter:
            response = waiter.get("/staff/waiter")

        self.assertIn("Ocupada", response.text)
        self.assertIn("3 comensales", response.text)
        self.assertIn(f'data-open-session="{session_id}"', response.text)
        self.assertIn("pedidos activos", response.text)

    def test_active_restaurant_switch_keeps_tenant_data_isolated(self):
        with self.client_as(1, active_restaurant_id=2) as owner:
            response = owner.get("/staff/waiter")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Playa", response.text)
        self.assertIn("P01", response.text)
        self.assertIn("Arroz Playa", response.text)
        self.assertNotIn("C01", response.text)
        self.assertNotIn("Arroz Centro", response.text)

    def test_workspace_has_responsive_and_touch_first_structure(self):
        with self.client_as(3) as waiter:
            response = waiter.get("/staff/waiter")

        self.assertIn('name="viewport"', response.text)
        self.assertIn('class="room-grid"', response.text)
        self.assertIn('class="table-card is-free"', response.text)
        self.assertIn('class="open-table-form"', response.text)
        self.assertIn('inputmode="numeric"', response.text)
        self.assertIn('id="sessionWorkspace"', response.text)
        self.assertIn("waiter.css", response.text)
        self.assertIn("waiter.js", response.text)
        self.assertNotIn("<table", response.text)

    def test_frontend_preserves_backend_authorization_and_idempotency_patterns(self):
        project_root = Path(__file__).resolve().parents[1]
        script = (project_root / "app/static/js/waiter.js").read_text(
            encoding="utf-8"
        )
        stylesheet = (project_root / "app/static/css/waiter.css").read_text(
            encoding="utf-8"
        )

        self.assertIn("credentials: \"same-origin\"", script)
        self.assertIn("idempotency_key: randomKey()", script)
        self.assertIn("button.disabled = true", script)
        self.assertIn("window.confirm", script)
        self.assertIn("await loadOrders()", script)
        self.assertIn("showAlert(error.message)", script)
        self.assertNotIn("OperationalTransaction", script)
        self.assertIn("min-height: 48px", stylesheet)
        self.assertIn("@media (max-width: 680px)", stylesheet)
        self.assertIn("prefers-reduced-motion", stylesheet)
