import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker

from app.core.security import verify_password
from app.models import Restaurant, User
from app.utils.demo_seed import DEMO_OWNER_EMAIL, DEMO_OWNER_PASSWORD

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STRONG_SECRET = "Render-generated-secret-for-tests-0123456789abcdef"
DEMO_PASSWORD = "Generated-by-render-7f3a9c"


def run_start_sequence(database_url: str, **overrides: str) -> subprocess.CompletedProcess[str]:
    """Same steps as scripts/render_start.sh, minus starting uvicorn."""
    environment = {
        **os.environ,
        "DATABASE_URL": database_url,
        "ENVIRONMENT": "production",
        "SECRET_KEY": STRONG_SECRET,
        "APP_URL": "https://hostai.onrender.com",
        "CORS_ORIGINS": "https://hostai.onrender.com",
        "SEED_DEMO_ON_EMPTY": "true",
        "DEMO_OWNER_PASSWORD": DEMO_PASSWORD,
        **overrides,
    }
    environment = {key: value for key, value in environment.items() if value is not None}
    migrate = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=PROJECT_ROOT, env=environment, capture_output=True, text=True, timeout=180,
    )
    if migrate.returncode != 0:
        return migrate
    return subprocess.run(
        [sys.executable, "-m", "app.utils.deploy_bootstrap"],
        cwd=PROJECT_ROOT, env=environment, capture_output=True, text=True, timeout=180,
    )


class DeployBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_url = f"sqlite:///{Path(self.temp_dir.name, 'render.db').as_posix()}"

    def tearDown(self):
        self.temp_dir.cleanup()

    def _counts(self) -> tuple[int, User | None]:
        engine = create_engine(self.database_url)
        try:
            with sessionmaker(bind=engine)() as db:
                restaurants = db.scalar(select(func.count()).select_from(Restaurant))
                owner = db.scalar(select(User).where(User.email == DEMO_OWNER_EMAIL))
                if owner is not None:
                    db.expunge(owner)
                return restaurants, owner
        finally:
            engine.dispose()

    def test_production_refuses_the_public_demo_password(self):
        result = run_start_sequence(self.database_url, DEMO_OWNER_PASSWORD="")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DEMO_OWNER_PASSWORD is required", result.stderr + result.stdout)
        self.assertEqual(self._counts()[0], 0)

    def test_short_demo_password_is_rejected(self):
        result = run_start_sequence(self.database_url, DEMO_OWNER_PASSWORD="corta")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self._counts()[0], 0)

    def test_seeds_once_with_private_password_and_never_overwrites(self):
        first = run_start_sequence(self.database_url)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn("demo seeded", first.stdout)
        restaurants, owner = self._counts()
        self.assertEqual(restaurants, 1)
        self.assertTrue(verify_password(DEMO_PASSWORD, owner.hashed_password))
        self.assertFalse(verify_password(DEMO_OWNER_PASSWORD, owner.hashed_password))

        # Simulate a change made by the restaurant, then a redeploy.
        engine = create_engine(self.database_url)
        with engine.begin() as connection:
            connection.execute(text("UPDATE restaurants SET name = 'Cambiado'"))
        engine.dispose()
        second = run_start_sequence(self.database_url)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("already has restaurants", second.stdout)
        engine = create_engine(self.database_url)
        with engine.connect() as connection:
            self.assertEqual(connection.scalar(text("SELECT name FROM restaurants")), "Cambiado")
        engine.dispose()

    def test_seeding_is_opt_in(self):
        result = run_start_sequence(self.database_url, SEED_DEMO_ON_EMPTY="false")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("not enabled", result.stdout)
        self.assertEqual(self._counts()[0], 0)


class RenderBlueprintTests(unittest.TestCase):
    def test_blueprint_generates_secrets_and_uses_the_start_script(self):
        blueprint = (PROJECT_ROOT / "render.yaml").read_text(encoding="utf-8")
        start_script = (PROJECT_ROOT / "scripts" / "render_start.sh").read_text(encoding="utf-8")

        self.assertIn("startCommand: bash scripts/render_start.sh", blueprint)
        self.assertIn("healthCheckPath: /health", blueprint)
        for secret in ("SECRET_KEY", "DEMO_OWNER_PASSWORD"):
            index = blueprint.index(f"key: {secret}")
            self.assertIn("generateValue: true", blueprint[index:index + 80])
        self.assertNotIn(DEMO_OWNER_PASSWORD, blueprint)
        self.assertIn("python -m alembic upgrade head", start_script)
        self.assertIn("python -m app.utils.deploy_bootstrap", start_script)
        self.assertIn("--no-access-log", start_script)


if __name__ == "__main__":
    unittest.main()
