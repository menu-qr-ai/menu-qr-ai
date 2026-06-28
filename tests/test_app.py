import json
import tempfile
import unittest
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
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

    def test_analytics_event_accepts_minimal_body(self):
        with TestClient(app) as client:
            response = client.post(
                "/api/analytics/events",
                json={"event_type": "menu_view"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["event_type"], "menu_view")
        self.assertIsNone(payload["restaurant_id"])
        self.assertIsNone(payload["dish_id"])
        self.assertIsNone(payload["language"])
        self.assertIsNone(payload["metadata"])

    def test_analytics_event_accepts_full_body_with_nulls(self):
        with TestClient(app) as client:
            response = client.post(
                "/api/analytics/events",
                json={
                    "restaurant_id": 1,
                    "event_type": "menu_view",
                    "dish_id": None,
                    "language": "es",
                    "metadata": {"source": "swagger"},
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["restaurant_id"], 1)
        self.assertEqual(payload["event_type"], "menu_view")
        self.assertIsNone(payload["dish_id"])
        self.assertEqual(payload["language"], "es")
        self.assertEqual(payload["metadata"], {"source": "swagger"})

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

    def test_dashboard_summary_returns_empty_state_without_events(self):
        with TestClient(app) as client:
            response = client.get("/api/dashboard/summary")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["summary"]["total_menu_views"], 0)
        self.assertEqual(payload["top_dishes"], [])
        self.assertEqual(payload["top_searches"], [])
        self.assertEqual(payload["insights"][0]["title"], "No hay suficientes datos todavia")

    def test_dashboard_summary_changes_with_analytics_events(self):
        with self.SessionTesting() as db:
            db.add_all(
                [
                    AnalyticsEvent(restaurant_id=1, event_type="menu_view"),
                    AnalyticsEvent(restaurant_id=1, event_type="dish_view", dish_id=1),
                    AnalyticsEvent(restaurant_id=1, event_type="dish_view", dish_id=1),
                    AnalyticsEvent(
                        restaurant_id=1,
                        event_type="search",
                        metadata_json=json.dumps({"search_query": "pizza"}),
                    ),
                    AnalyticsEvent(restaurant_id=1, event_type="language_change", language="en"),
                    AnalyticsEvent(restaurant_id=1, event_type="translation_request", language="en"),
                ]
            )
            db.commit()

        with TestClient(app) as client:
            response = client.get("/api/dashboard/summary?restaurant_id=1")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["summary"]["total_menu_views"], 1)
        self.assertEqual(payload["summary"]["total_dish_views"], 2)
        self.assertEqual(payload["summary"]["total_searches"], 1)
        self.assertEqual(payload["summary"]["total_language_changes"], 1)
        self.assertEqual(payload["summary"]["total_translation_requests"], 1)
        self.assertEqual(payload["summary"]["dish_view_menu_view_ratio"], 2)
        self.assertEqual(payload["summary"]["top_dish_name"], "Pizza Margarita")
        self.assertEqual(payload["top_dishes"][0]["name"], "Pizza Margarita")
        self.assertEqual(payload["top_dishes"][0]["views"], 2)
        self.assertEqual(payload["top_searches"][0], {"query": "pizza", "count": 1})
        self.assertEqual(payload["languages"][0], {"language": "en", "count": 2, "percentage": 100.0})
        self.assertGreaterEqual(len(payload["events_by_day"]), 1)

    def test_dashboard_summary_filters_by_restaurant_id(self):
        with self.SessionTesting() as db:
            db.add_all(
                [
                    AnalyticsEvent(restaurant_id=1, event_type="menu_view"),
                    AnalyticsEvent(restaurant_id=2, event_type="menu_view"),
                    AnalyticsEvent(restaurant_id=2, event_type="menu_view"),
                ]
            )
            db.commit()

        with TestClient(app) as client:
            response = client.get("/api/dashboard/summary?restaurant_id=2")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["restaurant_id"], 2)
        self.assertEqual(payload["summary"]["total_menu_views"], 2)

    def test_dashboard_range_today_filters_events(self):
        old_date = datetime.utcnow() - timedelta(days=2)
        with self.SessionTesting() as db:
            db.add_all(
                [
                    AnalyticsEvent(restaurant_id=1, event_type="menu_view"),
                    AnalyticsEvent(restaurant_id=1, event_type="menu_view", created_at=old_date),
                ]
            )
            db.commit()

        with TestClient(app) as client:
            response = client.get("/api/dashboard/summary?range=today")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["range"], "today")
        self.assertEqual(payload["summary"]["total_menu_views"], 1)

    def test_dashboard_range_7d_filters_events(self):
        with self.SessionTesting() as db:
            db.add_all(
                [
                    AnalyticsEvent(restaurant_id=1, event_type="search"),
                    AnalyticsEvent(
                        restaurant_id=1,
                        event_type="search",
                        created_at=datetime.utcnow() - timedelta(days=8),
                    ),
                ]
            )
            db.commit()

        with TestClient(app) as client:
            response = client.get("/api/dashboard/summary?range=7d")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["summary"]["total_searches"], 1)

    def test_dashboard_range_30d_filters_events(self):
        with self.SessionTesting() as db:
            db.add_all(
                [
                    AnalyticsEvent(restaurant_id=1, event_type="translation_request"),
                    AnalyticsEvent(
                        restaurant_id=1,
                        event_type="translation_request",
                        created_at=datetime.utcnow() - timedelta(days=31),
                    ),
                ]
            )
            db.commit()

        with TestClient(app) as client:
            response = client.get("/api/dashboard/summary?range=30d")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["summary"]["total_translation_requests"], 1)

    def test_dashboard_range_90d_filters_events(self):
        with self.SessionTesting() as db:
            db.add_all(
                [
                    AnalyticsEvent(restaurant_id=1, event_type="menu_view"),
                    AnalyticsEvent(
                        restaurant_id=1,
                        event_type="menu_view",
                        created_at=datetime.utcnow() - timedelta(days=91),
                    ),
                ]
            )
            db.commit()

        with TestClient(app) as client:
            response = client.get("/api/dashboard/summary?range=90d")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["summary"]["total_menu_views"], 1)

    def test_dashboard_range_all_includes_all_events(self):
        with self.SessionTesting() as db:
            db.add_all(
                [
                    AnalyticsEvent(restaurant_id=1, event_type="menu_view"),
                    AnalyticsEvent(
                        restaurant_id=1,
                        event_type="menu_view",
                        created_at=datetime.utcnow() - timedelta(days=120),
                    ),
                ]
            )
            db.commit()

        with TestClient(app) as client:
            response = client.get("/api/dashboard/summary?range=all")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["range"], "all")
        self.assertEqual(payload["summary"]["total_menu_views"], 2)

    def test_dashboard_insights_are_generated_from_real_events(self):
        with self.SessionTesting() as db:
            db.add_all(
                [
                    AnalyticsEvent(restaurant_id=1, event_type="menu_view"),
                    AnalyticsEvent(restaurant_id=1, event_type="menu_view"),
                    AnalyticsEvent(restaurant_id=1, event_type="dish_view", dish_id=1),
                    AnalyticsEvent(restaurant_id=1, event_type="language_change", language="en"),
                    AnalyticsEvent(
                        restaurant_id=1,
                        event_type="search",
                        metadata_json=json.dumps({"search_query": "tiramisu"}),
                    ),
                ]
            )
            db.commit()

        with TestClient(app) as client:
            response = client.get("/api/dashboard/summary?range=all")

        self.assertEqual(response.status_code, 200)
        insight_titles = [insight["title"] for insight in response.json()["insights"]]
        self.assertIn("Hay pocas visualizaciones de la carta", insight_titles)
        self.assertTrue(any("idioma" in title.lower() or "eventos con idioma" in title.lower() for title in insight_titles))

    def test_dashboard_page_renders_shell(self):
        with TestClient(app) as client:
            response = client.get("/admin/dashboard?restaurant_id=1")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Dashboard Inteligente", response.text)
        self.assertIn("dashboard.js", response.text)


if __name__ == "__main__":
    unittest.main()
