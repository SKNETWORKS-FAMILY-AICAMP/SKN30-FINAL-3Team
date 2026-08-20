import pytest
from fastapi.testclient import TestClient

import api.authentication
from core.config import Config
from domain.authentication.dependencies import get_authentication_context
from domain.authentication.models import AuthenticationContext, CurrentUser, UserRole
from domain.session import get_db_session
from main import create_app


def test_current_user_contract(config: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    """세션 확인은 사용자와 함께 새 CSRF 토큰을 돌려준다.

    토큰이 발급 응답에만 있으면 새로고침한 화면이 세션은 살아 있는데 쓰기만 403을 받는다.
    """
    app = create_app(config=config, readiness_probe=lambda request: True)
    app.dependency_overrides[get_authentication_context] = lambda: AuthenticationContext(
        user=CurrentUser(
            id=7,
            brokerage_id=3,
            login_id="developer",
            display_name="Developer",
            role=UserRole.OWNER,
        ),
        session_id=11,
        csrf_token_hash="unused",
    )
    app.dependency_overrides[get_db_session] = lambda: None
    monkeypatch.setattr(api.authentication, "rotate_csrf_token", lambda db, session_id: "fresh")

    with TestClient(app) as client:
        response = client.get("/api/v1/auth/me")

    assert response.status_code == 200
    assert response.json() == {
        "user": {
            "id": 7,
            "brokerage_id": 3,
            "login_id": "developer",
            "display_name": "Developer",
            "role": "OWNER",
        },
        "csrf_token": "fresh",
    }


def test_development_session_route_is_absent_when_disabled(config: Config) -> None:
    app = create_app(config=config, readiness_probe=lambda request: True)

    with TestClient(app) as client:
        response = client.post("/api/v1/auth/development-session")

    assert response.status_code == 404
