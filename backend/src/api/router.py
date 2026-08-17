from fastapi import APIRouter

from api.authentication import development_router
from api.authentication import router as authentication_router
from core.config import Config


def create_api_router(config: Config) -> APIRouter:
    router = APIRouter(prefix="/api/v1")
    router.include_router(authentication_router)
    if config.auth.development.enabled:
        router.include_router(development_router)
    return router
