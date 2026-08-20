from fastapi import APIRouter, Depends, Request, Response
from sqlmodel import Session

from api.schemas.authentication import (
    CurrentUserResponse,
    DevelopmentSessionResponse,
    SessionUserResponse,
)
from core.config import Config
from domain.authentication.dependencies import (
    get_authentication_context,
    require_csrf,
)
from domain.authentication.models import AuthenticationContext
from domain.authentication.service import (
    issue_development_session,
    revoke_session,
    rotate_csrf_token,
)
from domain.session import get_app_config, get_db_session

router = APIRouter(prefix="/auth", tags=["authentication"])
development_router = APIRouter(prefix="/auth", tags=["authentication"])


@development_router.post(
    "/development-session",
    response_model=DevelopmentSessionResponse,
)
def create_development_session(
    response: Response,
    config: Config = Depends(get_app_config),
    db: Session = Depends(get_db_session),
) -> DevelopmentSessionResponse:
    issued = issue_development_session(db, config)
    response.set_cookie(
        key=config.auth.session.cookie_name,
        value=issued.session_token,
        httponly=True,
        secure=config.secure_cookie,
        samesite="lax",
        domain=config.auth.session.cookie_domain,
        path="/",
        max_age=config.auth.session.absolute_timeout_minutes * 60,
    )
    return DevelopmentSessionResponse(
        user=CurrentUserResponse.from_domain(issued.user),
        csrf_token=issued.csrf_token,
    )


@router.get("/me", response_model=SessionUserResponse)
def me(
    context: AuthenticationContext = Depends(get_authentication_context),
    db: Session = Depends(get_db_session),
) -> SessionUserResponse:
    return SessionUserResponse(
        user=CurrentUserResponse.from_domain(context.user),
        csrf_token=rotate_csrf_token(db, context.session_id),
    )


@router.delete("/session", status_code=204, dependencies=[Depends(require_csrf)])
def delete_session(
    request: Request,
    response: Response,
    context: AuthenticationContext = Depends(get_authentication_context),
    config: Config = Depends(get_app_config),
    db: Session = Depends(get_db_session),
) -> None:
    del context
    session_token = request.cookies.get(config.auth.session.cookie_name)
    if session_token:
        revoke_session(db, session_token)
    response.delete_cookie(
        key=config.auth.session.cookie_name,
        domain=config.auth.session.cookie_domain,
        path="/",
        secure=config.secure_cookie,
        httponly=True,
        samesite="lax",
    )
