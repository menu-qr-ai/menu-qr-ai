from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging, log_request_middleware
from app.models import Category, Dish, Restaurant  # noqa: F401
from app.routers import admin, ai, api, health, menu, restaurant, translation


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


def create_app() -> FastAPI:
    configure_logging()
    application = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.middleware("http")(log_request_middleware)
    register_exception_handlers(application)

    application.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")
    application.include_router(health.router)
    application.include_router(menu.router)
    application.include_router(ai.router)
    application.include_router(translation.router)
    application.include_router(restaurant.router)
    application.include_router(api.router)
    application.include_router(admin.router)
    return application


app = create_app()
