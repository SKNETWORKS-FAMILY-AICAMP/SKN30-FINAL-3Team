from fastapi.testclient import TestClient

from core.config import Config
from domain.authentication.dependencies import get_current_user
from domain.authentication.models import CurrentUser, UserRole
from main import create_app


def test_current_user_contract(config: Config) -> None:
    app = create_app(config=config, readiness_probe=lambda request: True)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=7,
        brokerage_id=3,
        login_id="developer",
        display_name="Developer",
        role=UserRole.OWNER,
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/auth/me")

    assert response.status_code == 200
    assert response.json() == {
        "id": 7,
        "brokerage_id": 3,
        "login_id": "developer",
        "display_name": "Developer",
        "role": "OWNER",
    }


def test_development_session_route_is_absent_when_disabled(config: Config) -> None:
    app = create_app(config=config, readiness_probe=lambda request: True)

    with TestClient(app) as client:
        response = client.post("/api/v1/auth/development-session")

    assert response.status_code == 404
