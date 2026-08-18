from __future__ import annotations

from collections.abc import Callable

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from api.health import database_is_ready
from api.health import router as health_router
from api.router import create_api_router
from core.config import Config, get_config
from core.errors import ApplicationError, AuthenticationError
from core.logging import configure_logging
from core.request_context import RequestContextMiddleware
from domain.engine import create_database_engine

logger = structlog.get_logger()


def create_app(
    config: Config | None = None,
    readiness_probe: Callable[[Request], bool] | None = None,
) -> FastAPI:
    resolved_config = config or get_config()
    configure_logging(resolved_config.log)

    app = FastAPI(
        title="Brokerage Backend",
        version="0.1.0",
        docs_url="/docs" if resolved_config.app.openapi_enabled else None,
        redoc_url=None,
        openapi_url=("/openapi.json" if resolved_config.app.openapi_enabled else None),
    )
    app.state.config = resolved_config
    app.state.db_engine = create_database_engine(resolved_config)
    app.state.readiness_probe = readiness_probe or database_is_ready

    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_config.http.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["Content-Type", "X-CSRF-Token", "X-Request-ID"],
    )
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=resolved_config.http.allowed_hosts,
    )
    app.add_middleware(RequestContextMiddleware)

    app.include_router(health_router)
    app.include_router(create_api_router(resolved_config))

    @app.exception_handler(AuthenticationError)
    async def authentication_error_handler(
        request: Request, exc: AuthenticationError
    ) -> JSONResponse:
        status_code = 403 if exc.code in {"FORBIDDEN", "INVALID_CSRF_TOKEN"} else 401
        return JSONResponse(
            status_code=status_code,
            content={
                "code": exc.code,
                "message": exc.message,
                "request_id": request.state.request_id,
            },
        )

    @app.exception_handler(ApplicationError)
    async def application_error_handler(request: Request, exc: ApplicationError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.code,
                "message": exc.message,
                "request_id": request.state.request_id,
            },
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_request_error", error_type=type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content={
                "code": "INTERNAL_SERVER_ERROR",
                "message": "an unexpected error occurred",
                "request_id": request.state.request_id,
            },
        )

    return app


app = create_app()
