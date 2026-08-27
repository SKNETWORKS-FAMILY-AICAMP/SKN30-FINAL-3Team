import pytest
from fastapi.testclient import TestClient

import api.authentication
from core.config import Config
from domain.authentication.dependencies import get_authentication_context
from domain.authentication.models import AuthenticationContext, CurrentUser, UserRole
from domain.authentication.service import IssuedSession, hash_token
from domain.session import get_db_session
from main import create_app

CSRF_TOKEN = "stable-csrf-token"


def authentication_context() -> AuthenticationContext:
    return AuthenticationContext(
        user=CurrentUser(
            id=7,
            brokerage_id=3,
            login_id="developer",
            display_name="Developer",
            role=UserRole.OWNER,
        ),
        session_id=11,
        csrf_token_hash=hash_token(CSRF_TOKEN),
    )


def test_current_user_rehydrates_the_same_csrf_token_without_rotation(config: Config) -> None:
    """세션 확인은 브라우저가 보관한 토큰을 검증해 그대로 돌려준다.

    조회할 때마다 서버 해시를 바꾸지 않아 새로고침과 여러 탭이 서로의 토큰을 무효화하지 않는다.
    """
    app = create_app(config=config, readiness_probe=lambda request: True)
    app.dependency_overrides[get_authentication_context] = authentication_context

    with TestClient(app) as client:
        client.cookies.set(config.auth.session.csrf_cookie_name, CSRF_TOKEN)
        first_response = client.get("/api/v1/auth/me")
        second_response = client.get("/api/v1/auth/me")

    expected = {
        "user": {
            "id": 7,
            "brokerage_id": 3,
            "login_id": "developer",
            "display_name": "Developer",
            "role": "OWNER",
        },
        "csrf_token": CSRF_TOKEN,
    }
    assert first_response.status_code == 200
    assert first_response.headers["Cache-Control"] == "no-store"
    assert first_response.json() == expected
    assert second_response.status_code == 200
    assert second_response.json() == expected


def test_current_user_rejects_a_missing_csrf_cookie(config: Config) -> None:
    app = create_app(config=config, readiness_probe=lambda request: True)
    app.dependency_overrides[get_authentication_context] = authentication_context

    with TestClient(app) as client:
        response = client.get("/api/v1/auth/me")

    assert response.status_code == 403
    assert response.json()["code"] == "INVALID_CSRF_TOKEN"


def test_development_session_sets_session_and_csrf_cookies(
    make_config, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = make_config(
        {
            "APP_ENV": "dev",
            "DB_TARGET": "development",
            "AUTH_DEVELOPMENT_ENABLED": "true",
            "AUTH_DEVELOPMENT_BROKERAGE_ID": "3",
            "AUTH_DEVELOPMENT_LOGIN_ID": "developer",
            "AUTH_SESSION_IDLE_TIMEOUT_MINUTES": "30",
            "AUTH_SESSION_ABSOLUTE_TIMEOUT_MINUTES": "720",
        }
    )
    issued = IssuedSession(
        session_token="session-token",
        csrf_token=CSRF_TOKEN,
        user=authentication_context().user,
    )
    monkeypatch.setattr(api.authentication, "issue_development_session", lambda db, config: issued)
    app = create_app(config=config, readiness_probe=lambda request: True)
    app.dependency_overrides[get_db_session] = lambda: None

    with TestClient(app) as client:
        response = client.post("/api/v1/auth/development-session")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.cookies.get(config.auth.session.cookie_name) == "session-token"
    assert response.cookies.get(config.auth.session.csrf_cookie_name) == CSRF_TOKEN
    set_cookie_headers = response.headers.get_list("set-cookie")
    assert all("HttpOnly" in header for header in set_cookie_headers)
    assert all("Secure" in header for header in set_cookie_headers)
    assert all("SameSite=lax" in header for header in set_cookie_headers)
    assert all("Max-Age=43200" in header for header in set_cookie_headers)


def test_logout_clears_session_and_csrf_cookies(
    config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    revoked_tokens: list[str] = []
    monkeypatch.setattr(
        api.authentication,
        "revoke_session",
        lambda db, session_token: revoked_tokens.append(session_token),
    )
    app = create_app(config=config, readiness_probe=lambda request: True)
    app.dependency_overrides[get_authentication_context] = authentication_context
    app.dependency_overrides[get_db_session] = lambda: None

    with TestClient(app) as client:
        client.cookies.set(config.auth.session.cookie_name, "session-token")
        client.cookies.set(config.auth.session.csrf_cookie_name, CSRF_TOKEN)
        response = client.delete(
            "/api/v1/auth/session",
            headers={"X-CSRF-Token": CSRF_TOKEN},
        )

    assert response.status_code == 204
    assert revoked_tokens == ["session-token"]
    set_cookie_headers = response.headers.get_list("set-cookie")
    assert any(
        header.startswith(f"{config.auth.session.cookie_name}=") for header in set_cookie_headers
    )
    assert any(
        header.startswith(f"{config.auth.session.csrf_cookie_name}=")
        for header in set_cookie_headers
    )
    assert all("Max-Age=0" in header for header in set_cookie_headers)


def test_development_session_route_is_absent_when_disabled(config: Config) -> None:
    app = create_app(config=config, readiness_probe=lambda request: True)

    with TestClient(app) as client:
        response = client.post("/api/v1/auth/development-session")

    assert response.status_code == 404


def test_development_session_route_is_absent_in_test_even_when_configured(make_config) -> None:
    config = make_config(
        {
            "AUTH_DEVELOPMENT_ENABLED": "true",
            "AUTH_DEVELOPMENT_BROKERAGE_ID": "3",
            "AUTH_DEVELOPMENT_LOGIN_ID": "developer",
        }
    )
    app = create_app(config=config, readiness_probe=lambda request: True)

    with TestClient(app) as client:
        response = client.post("/api/v1/auth/development-session")

    assert response.status_code == 404
