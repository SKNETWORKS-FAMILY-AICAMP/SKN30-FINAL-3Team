from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import asynccontextmanager

import structlog
from brokerage_ai import load_ai_config
from brokerage_ai.core.config import F2ProviderStatus
from brokerage_ai.f2 import F2Runtime, create_f2_runtime
from fastapi import FastAPI, Request
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from api.health import database_is_ready
from api.health import router as health_router
from api.router import create_api_router
from core.config import Config, get_config
from core.errors import (
    ApplicationError,
    AuthenticationError,
    F2ProcessingError,
    F2UnavailableError,
)
from core.health_host import HealthAwareTrustedHostMiddleware
from core.logging import configure_logging, exception_location
from core.request_context import REQUEST_ID_HEADER, RequestContextMiddleware
from domain.engine import create_database_engine

logger = structlog.get_logger()


def _is_public_api(request: Request) -> bool:
    path = request.url.path
    return path == "/api/v1" or path.startswith("/api/v1/")


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    response_headers = dict(headers or {})
    response_headers[REQUEST_ID_HEADER] = request.state.request_id
    return JSONResponse(
        status_code=status_code,
        headers=response_headers,
        content={
            "code": code,
            "message": message,
            "request_id": request.state.request_id,
        },
    )


def create_app(
    config: Config | None = None,
    readiness_probe: Callable[[Request], bool] | None = None,
    f2_runtime_factory: Callable[[], F2Runtime] | None = None,
) -> FastAPI:
    resolved_config = config or get_config()
    configure_logging(resolved_config.log)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime: F2Runtime | None = None
        if f2_runtime_factory is not None:
            runtime = f2_runtime_factory()
        else:
            ai_config = load_ai_config(resolved_config.app.environment.value)
            if ai_config.f2.provider_status is F2ProviderStatus.ACTIVE:
                runtime = create_f2_runtime(ai_config)
        app.state.f2_pipeline = runtime.pipeline if runtime is not None else None
        try:
            yield
        finally:
            if runtime is not None:
                await runtime.close()

    app = FastAPI(
        title="Brokerage Backend",
        version="0.1.0",
        docs_url="/docs" if resolved_config.app.openapi_enabled else None,
        redoc_url=None,
        openapi_url=("/openapi.json" if resolved_config.app.openapi_enabled else None),
        lifespan=lifespan,
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
        HealthAwareTrustedHostMiddleware,
        allowed_hosts=resolved_config.http.allowed_hosts,
    )
    app.add_middleware(RequestContextMiddleware)

    app.include_router(health_router)
    app.include_router(create_api_router(resolved_config))

    @app.exception_handler(StarletteHTTPException)
    async def framework_http_error_handler(
        request: Request, exc: StarletteHTTPException
    ) -> Response:
        if _is_public_api(request) and exc.status_code in {404, 405}:
            code, message = (
                ("NOT_FOUND", "resource is not found")
                if exc.status_code == 404
                else ("METHOD_NOT_ALLOWED", "method is not allowed")
            )
            return _error_response(
                request,
                status_code=exc.status_code,
                code=code,
                message=message,
                headers=exc.headers,
            )
        return await http_exception_handler(request, exc)

    @app.exception_handler(RequestValidationError)
    async def framework_validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> Response:
        if _is_public_api(request):
            return _error_response(
                request,
                status_code=422,
                code="VALIDATION_FAILED",
                message="request validation failed",
            )
        return await request_validation_exception_handler(request, exc)

    @app.exception_handler(AuthenticationError)
    async def authentication_error_handler(
        request: Request, exc: AuthenticationError
    ) -> JSONResponse:
        status_code = 403 if exc.code in {"FORBIDDEN", "INVALID_CSRF_TOKEN"} else 401
        return _error_response(
            request,
            status_code=status_code,
            code=exc.code,
            message=exc.message,
        )

    @app.exception_handler(ApplicationError)
    async def application_error_handler(request: Request, exc: ApplicationError) -> JSONResponse:
        if isinstance(exc, F2UnavailableError | F2ProcessingError):
            diagnostic = exc.__cause__ if isinstance(exc.__cause__, BaseException) else exc
            logger.error(
                "ai_terminal_failure",
                component="ai",
                source="f2",
                request_id=request.state.request_id,
                status_code=exc.status_code,
                error_code=exc.code,
                failure_stage="F2_ANALYSIS",
                error_type=type(diagnostic).__name__,
                error_location=exception_location(diagnostic),
            )
        return _error_response(
            request,
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "unhandled_request_error",
            component="backend",
            request_id=request.state.request_id,
            status_code=500,
            error_code="INTERNAL_SERVER_ERROR",
            error_type=type(exc).__name__,
            error_location=exception_location(exc),
        )
        return _error_response(
            request,
            status_code=500,
            code="INTERNAL_SERVER_ERROR",
            message="an unexpected error occurred",
        )

    return app


app = create_app()
