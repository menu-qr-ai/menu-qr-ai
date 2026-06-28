import tempfile
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app
from app.models import AnalyticsEvent, Category, Dish, Restaurant


class AppSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.engine = create_engine(
            f"sqlite:///{cls.temp_dir.name}/test.db",
            connect_args={"check_same_thread": False},
        )
        cls.SessionTesting = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)
        Base.metadata.create_all(bind=cls.engine)
        cls.seed_database()

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
    def seed_database(cls):
        with cls.SessionTesting() as db:
            restaurant = Restaurant(id=1, name="Demo Restaurant")
            category = Category(id=1, name="Pizzas", restaurant_id=1)
            dish = Dish(
                id=1,
                name="Pizza Margarita",
                description="Classic pizza with tomato and cheese",
                price=9.99,
                ingredients="Tomato, mozzarella, basil",
                allergens="Gluten, lactose",
                image="",
                category_id=1,
                restaurant_id=1,
            )
            db.add_all([restaurant, category, dish])
            db.commit()

    def setUp(self):
        with self.SessionTesting() as db:
            db.execute(delete(AnalyticsEvent))
            db.commit()

    def test_health_route_works(self):
        with TestClient(app) as client:
            response = client.get("/test")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})

    def test_health_route_checks_database(self):
        with TestClient(app) as client:
            response = client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["database"], "ok")

    def test_api_root_exposes_environment(self):
        with TestClient(app) as client:
            response = client.get("/api")

        self.assertEqual(response.status_code, 200)
        self.assertIn("name", response.json())

    def test_api_plans_are_available(self):
        with TestClient(app) as client:
            response = client.get("/api/plans")

        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.json()["plans"]), 3)

    def test_restaurants_endpoint_uses_schema(self):
        with TestClient(app) as client:
            response = client.get("/restaurants")

        self.assertEqual(response.status_code, 200)
        self.assertIn("id", response.json()[0])

    def test_menu_page_renders_with_assets_and_data(self):
        with TestClient(app) as client:
            response = client.get("/menu")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Platos disponibles", response.text)
        self.assertIn("languageSelect", response.text)
        self.assertIn("menuSearch", response.text)
        self.assertIn("window.menuData", response.text)

    def test_admin_dashboard_renders(self):
        with TestClient(app) as client:
            response = client.get("/admin")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Panel de administracion", response.text)
        self.assertIn("Suscripciones", response.text)
        self.assertIn("Analitica", response.text)

    def test_static_assets_are_served(self):
        with TestClient(app) as client:
            css_response = client.get("/static/css/style.css")
            js_response = client.get("/static/js/app.js")

        self.assertEqual(css_response.status_code, 200)
        self.assertEqual(js_response.status_code, 200)

    def test_ai_route_is_stable_without_openai_key(self):
        with TestClient(app) as client:
            response = client.get("/ai/translate-dish/1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"error": "No OPENAI_API_KEY"})

    def test_analytics_event_can_be_created(self):
        with TestClient(app) as client:
            response = client.post(
                "/api/analytics/events",
                json={
                    "restaurant_id": 1,
                    "event_type": "menu_view",
                    "language": "en",
                    "metadata": {"source": "test"},
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["event_type"], "menu_view")
        self.assertEqual(payload["metadata"], {"source": "test"})
        self.assertIn("created_at", payload)

    def test_analytics_event_rejects_invalid_type(self):
        with TestClient(app) as client:
            response = client.post(
                "/api/analytics/events",
                json={"restaurant_id": 1, "event_type": "bad_event"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_analytics_event_type")

    def test_recent_analytics_events_returns_list(self):
        with TestClient(app) as client:
            client.post("/api/analytics/events", json={"restaurant_id": 1, "event_type": "menu_view"})
            response = client.get("/api/analytics/events/recent?restaurant_id=1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)

    def test_analytics_events_count_returns_counter(self):
        with TestClient(app) as client:
            client.post("/api/analytics/events", json={"restaurant_id": 1, "event_type": "search"})
            client.post("/api/analytics/events", json={"restaurant_id": 1, "event_type": "search"})
            response = client.get("/api/analytics/events/count?event_type=search&restaurant_id=1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 2)


if __name__ == "__main__":
    unittest.main()
