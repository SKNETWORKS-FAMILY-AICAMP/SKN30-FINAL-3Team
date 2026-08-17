from collections.abc import Callable

from fastapi import Depends, Header, Request
from sqlmodel import Session

from core.config import Config
from core.errors import AuthenticationError
from domain.authentication.models import AuthenticationContext, CurrentUser, UserRole
from domain.authentication.service import authenticate_session, validate_csrf
from domain.session import get_app_config, get_db_session


def get_authentication_context(
    request: Request,
    config: Config = Depends(get_app_config),
    db: Session = Depends(get_db_session),
) -> AuthenticationContext:
    session_token = request.cookies.get(config.auth.session.cookie_name)
    if not session_token:
        raise AuthenticationError("UNAUTHENTICATED", "authentication is required")
    return authenticate_session(db, config, session_token)


def get_current_user(
    context: AuthenticationContext = Depends(get_authentication_context),
) -> CurrentUser:
    return context.user


def require_csrf(
    context: AuthenticationContext = Depends(get_authentication_context),
    csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
) -> None:
    validate_csrf(context, csrf_token)


def require_roles(*roles: UserRole) -> Callable[[CurrentUser], CurrentUser]:
    allowed = set(roles)

    def dependency(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in allowed:
            raise AuthenticationError("FORBIDDEN", "permission is denied")
        return user

    return dependency
