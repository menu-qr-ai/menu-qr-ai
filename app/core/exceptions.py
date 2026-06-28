import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette import status


logger = logging.getLogger("app.exceptions")


class AppError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        code: str = "app_error",
    ) -> None:
        self.message = message
        self.status_code = status_code
        self.code = code


def _error_response(request: Request, status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "path": request.url.path,
            }
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        logger.warning(
            "app_error code=%s path=%s message=%s",
            exc.code,
            request.url.path,
            exc.message,
        )
        return _error_response(request, exc.status_code, exc.code, exc.message)

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unexpected_error path=%s", request.url.path, exc_info=exc)
        return _error_response(
            request,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "internal_server_error",
            "No se pudo completar la operacion.",
        )

