from fastapi.testclient import TestClient

from core.config import Config
from main import create_app


def test_live_health_does_not_require_database(config: Config) -> None:
    app = create_app(config=config, readiness_probe=lambda request: True)

    with TestClient(app) as client:
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-ID"]


def test_ready_health_returns_503_when_probe_fails(config: Config) -> None:
    app = create_app(config=config, readiness_probe=lambda request: False)

    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


def test_alb_private_host_is_allowed_only_for_health(config: Config) -> None:
    app = create_app(config=config, readiness_probe=lambda request: True)

    with TestClient(app) as client:
        health = client.get("/health/ready", headers={"Host": "10.30.0.42:8000"})
        api = client.get("/api/v1/property-ledger", headers={"Host": "10.30.0.42:8000"})

    assert health.status_code == 200
    assert api.status_code == 400
