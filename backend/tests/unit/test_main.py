import asyncio
from types import SimpleNamespace
from typing import cast

import pytest
from brokerage_ai.core.config import AiConfig, F2ProviderStatus
from brokerage_ai.f2 import F2Pipeline, F2Runtime

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
    ai_config = cast(
        AiConfig,
        SimpleNamespace(f2=SimpleNamespace(provider_status=F2ProviderStatus.ACTIVE)),
    )
    runtime = FakeF2Runtime()

    def load_config(profile: str) -> AiConfig:
        loaded_profiles.append(profile)
        return ai_config

    def create_runtime(received: AiConfig) -> F2Runtime:
        assert received is ai_config
        return cast(F2Runtime, runtime)

    monkeypatch.setattr(main, "load_ai_config", load_config)
    monkeypatch.setattr(main, "create_f2_runtime", create_runtime)

    async def run_lifespan() -> None:
        app = create_app(config=config, readiness_probe=lambda _request: True)
        async with app.router.lifespan_context(app):
            assert loaded_profiles == ["dev"]

    asyncio.run(run_lifespan())

    assert runtime.closed is True


def test_offline_f2_does_not_initialize_runtime(
    make_config, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = make_config({"APP_ENV": "dev", "DB_TARGET": "development"})
    ai_config = cast(
        AiConfig,
        SimpleNamespace(f2=SimpleNamespace(provider_status=F2ProviderStatus.OFFLINE)),
    )
    monkeypatch.setattr(main, "load_ai_config", lambda _profile: ai_config)

    def unexpected_runtime(_config: AiConfig) -> F2Runtime:
        raise AssertionError("offline F2 must not initialize its runtime")

    monkeypatch.setattr(main, "create_f2_runtime", unexpected_runtime)

    async def run_lifespan() -> None:
        app = create_app(config=config, readiness_probe=lambda _request: True)
        async with app.router.lifespan_context(app):
            assert app.state.f2_pipeline is None

    asyncio.run(run_lifespan())


def test_offline_f2_does_not_call_injected_runtime_factory(
    make_config, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = make_config({"APP_ENV": "dev", "DB_TARGET": "development"})
    ai_config = cast(
        AiConfig,
        SimpleNamespace(f2=SimpleNamespace(provider_status=F2ProviderStatus.OFFLINE)),
    )
    monkeypatch.setattr(main, "load_ai_config", lambda _profile: ai_config)

    def unexpected_factory() -> F2Runtime:
        raise AssertionError("offline F2 must not call an injected runtime factory")

    async def run_lifespan() -> None:
        app = create_app(
            config=config,
            readiness_probe=lambda _request: True,
            f2_runtime_factory=unexpected_factory,
        )
        async with app.router.lifespan_context(app):
            assert app.state.f2_pipeline is None

    asyncio.run(run_lifespan())
