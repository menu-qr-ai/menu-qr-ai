import logging
import sys
import time
from collections.abc import Awaitable, Callable

from fastapi import Request, Response

from app.core.config import settings
from app.core.version import APP_NAME, BUILD, VERSION


def configure_logging() -> None:
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )
    logging.getLogger("app.startup").info("app_configured name=%s version=%s build=%s", APP_NAME, VERSION, BUILD)


async def log_request_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    logger = logging.getLogger("app.requests")
    started_at = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
    logger.info(
        "request_completed method=%s path=%s status=%s duration_ms=%s",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    response.headers["X-Response-Time-Ms"] = str(duration_ms)
    return response
