import os
from pathlib import Path

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE = BASE_DIR / ".env"


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(ENV_FILE)


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_csv(
    value: str | None,
    *,
    default: tuple[str, ...],
) -> tuple[str, ...]:
    if not value:
        return default
    return tuple(item.strip() for item in value.split(",") if item.strip())


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    app_name: str = Field(default_factory=lambda: os.getenv("APP_NAME", "Menu QR AI"))
    app_url: str = Field(default_factory=lambda: os.getenv("APP_URL", "http://127.0.0.1:8000"))
    environment: str = Field(default_factory=lambda: os.getenv("ENVIRONMENT", "development"))
    debug: bool = Field(default_factory=lambda: _parse_bool(os.getenv("DEBUG"), default=False))
    database_url: str = Field(default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///./menu.db"))
    openai_api_key: str | None = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    openai_model: str = Field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
    secret_key: str = Field(default_factory=lambda: os.getenv("SECRET_KEY", "change-me-in-production"))
    cors_origins: tuple[str, ...] = Field(
        default_factory=lambda: _parse_csv(
            os.getenv("CORS_ORIGINS"),
            default=(
                "http://127.0.0.1:8000",
                "http://localhost:8000",
            ),
        )
    )
    session_max_age_seconds: int = Field(
        default_factory=lambda: int(
            os.getenv("SESSION_MAX_AGE_SECONDS", str(60 * 60 * 12))
        ),
        ge=300,
        le=60 * 60 * 24 * 30,
    )
    login_rate_limit_attempts: int = Field(
        default_factory=lambda: int(
            os.getenv("LOGIN_RATE_LIMIT_ATTEMPTS", "5")
        ),
        ge=2,
        le=100,
    )
    login_rate_limit_window_seconds: int = Field(
        default_factory=lambda: int(
            os.getenv("LOGIN_RATE_LIMIT_WINDOW_SECONDS", "900")
        ),
        ge=60,
        le=60 * 60 * 24,
    )
    log_level: str = Field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    templates_dir: Path = BASE_DIR / "app" / "templates"
    static_dir: Path = BASE_DIR / "app" / "static"

    @field_validator("environment", "log_level")
    @classmethod
    def normalize_lowercase(cls, value: str) -> str:
        return value.strip().lower()

    @model_validator(mode="after")
    def validate_security_configuration(self) -> "Settings":
        valid_environments = {
            "dev",
            "development",
            "local",
            "test",
            "testing",
            "prod",
            "production",
        }
        if self.environment not in valid_environments:
            raise ValueError("ENVIRONMENT is not recognized")
        if self.is_production:
            if (
                len(self.secret_key) < 32
                or len(set(self.secret_key)) < 16
                or self.secret_key == "change-me-in-production"
            ):
                raise ValueError(
                    "SECRET_KEY must be a strong value in production"
                )
            if not self.app_url.lower().startswith("https://"):
                raise ValueError("APP_URL must use HTTPS in production")
            if "*" in self.cors_origins:
                raise ValueError(
                    "CORS_ORIGINS cannot contain '*' in production"
                )
        return self

    @property
    def is_development(self) -> bool:
        return self.environment.lower() in {"dev", "development", "local"}

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"prod", "production"}

    @property
    def is_test(self) -> bool:
        return self.environment.lower() in {"test", "testing"}

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def cors_allow_credentials(self) -> bool:
        return "*" not in self.cors_origins

    @property
    def trusted_web_origins(self) -> tuple[str, ...]:
        values = {
            self.app_url.rstrip("/"),
            *(
                origin.rstrip("/")
                for origin in self.cors_origins
                if origin != "*"
            ),
        }
        return tuple(sorted(values))


settings = Settings()
