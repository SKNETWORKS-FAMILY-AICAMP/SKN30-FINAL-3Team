from typing import cast

import pytest
from brokerage_ai.core.config import AiConfig
from brokerage_ai.f2 import F2Pipeline, F2Runtime
from fastapi.testclient import TestClient

import main
from main import create_app


class FakeF2Runtime:
    def __init__(self) -> None:
        self.pipeline = cast(F2Pipeline, object())
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def test_f2_runtime_accepts_dev_ai_profile(make_config, monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config(
        {
            "APP_ENV": "dev",
            "DB_TARGET": "development",
            "F2_ENABLED": "true",
        }
    )
    loaded_profiles: list[str] = []
    ai_config = cast(AiConfig, object())
    runtime = FakeF2Runtime()

    def load_config(profile: str) -> AiConfig:
        loaded_profiles.append(profile)
        return ai_config

    def create_runtime(received: AiConfig) -> F2Runtime:
        assert received is ai_config
        return cast(F2Runtime, runtime)

    monkeypatch.setattr(main, "load_ai_config", load_config)
    monkeypatch.setattr(main, "create_f2_runtime", create_runtime)

    with TestClient(create_app(config=config, readiness_probe=lambda _request: True)):
        assert loaded_profiles == ["dev"]

    assert runtime.closed is True
