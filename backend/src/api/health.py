from collections.abc import Callable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from api.schemas.health import HealthResponse

router = APIRouter(prefix="/health", tags=["health"])


def database_is_ready(request: Request) -> bool:
    with request.app.state.db_engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return True


@router.get("/live", response_model=HealthResponse)
def live() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/ready", response_model=HealthResponse)
def ready(request: Request) -> HealthResponse | JSONResponse:
    probe: Callable[[Request], bool] = request.app.state.readiness_probe
    try:
        if probe(request):
            return HealthResponse(status="ok")
    except Exception:
        pass
    return JSONResponse(status_code=503, content={"status": "unavailable"})
