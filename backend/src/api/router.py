from fastapi import APIRouter

from api.authentication import development_router
from api.authentication import router as authentication_router
from api.f2 import router as f2_router
from api.f3_runs import router as f3_runs_router
from api.property_ledger import router as property_ledger_router
from api.time_keeper import router as time_keeper_router
from core.config import AppEnvironment, Config


def create_api_router(config: Config) -> APIRouter:
    router = APIRouter(prefix="/api/v1")
    router.include_router(authentication_router)
    router.include_router(property_ledger_router)
    router.include_router(f2_router)
    router.include_router(f3_runs_router)
    router.include_router(time_keeper_router)
    if config.auth.development.enabled and config.app.environment in {
        AppEnvironment.LOCAL,
        AppEnvironment.DEV,
    }:
        router.include_router(development_router)
    return router
