from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging, log_request_middleware
from app.core.security_headers import SecurityHeadersMiddleware
from app.core.session import SignedSessionMiddleware
from app.models import Category, CustomerSession, Dish, InventoryItem, KitchenTicket, KitchenTicketLine, Order, OrderLine, Restaurant, RestaurantMembership, RestaurantTable, ServiceSession, User, Zone  # noqa: F401
from app.routers import access, admin, ai, analytics, api, auth, business, customer, dashboard, dining, health, inventory, kitchen, kitchen_workspace, menu, operations, orders, payments, prediction, restaurant, restaurants, translation, waiter, workspace


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
        allow_methods=[
            "GET",
            "POST",
            "PUT",
            "PATCH",
            "DELETE",
            "OPTIONS",
        ],
        allow_headers=[
            "Accept",
            "Content-Type",
            "X-CSRF-Token",
        ],
    )
    application.add_middleware(
        SignedSessionMiddleware,
        secret_key=settings.secret_key,
        https_only=settings.is_production,
        max_age=settings.session_max_age_seconds,
        trusted_origins=settings.trusted_web_origins,
    )
    application.add_middleware(
        SecurityHeadersMiddleware,
        production=settings.is_production,
    )
    application.middleware("http")(log_request_middleware)
    register_exception_handlers(application)

    application.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")
    application.include_router(health.router)
    application.include_router(auth.router)
    application.include_router(access.router)
    application.include_router(workspace.router)
    application.include_router(menu.router)
    application.include_router(customer.router)
    application.include_router(ai.router)
    application.include_router(translation.router)
    application.include_router(analytics.router)
    application.include_router(business.router)
    application.include_router(dining.router)
    application.include_router(dashboard.router)
    application.include_router(inventory.router)
    application.include_router(kitchen.router)
    application.include_router(kitchen_workspace.router)
    application.include_router(operations.router)
    application.include_router(orders.router)
    application.include_router(payments.router)
    application.include_router(waiter.router)
    application.include_router(prediction.router)
    application.include_router(restaurants.router)
    application.include_router(restaurant.router)
    application.include_router(api.router)
    application.include_router(admin.router)
    return application


app = create_app()
