import unittest

from fastapi.testclient import TestClient

from app.main import app


class AppSmokeTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
