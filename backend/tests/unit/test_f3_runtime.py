"""F3 모델 설정·capability·provider 조립 경계."""

from __future__ import annotations

from typing import cast

import pytest
from brokerage_ai.core.types import ProviderKind
from brokerage_ai.f3 import InputPrivacyMode
from brokerage_ai.providers.ports import LlmProvider
from brokerage_ai.runtime import AiRuntime
from sqlmodel import Session

from core.errors import ConfigurationError
from domain.agent_execution.models import AgentRun, AiModelConfig
from f3_runtime import _route, build_bindings


class FakeProvider:
    kind = ProviderKind.VLLM


class FakeRegistry:
    def get_llm(self, kind: ProviderKind, endpoint_alias: str | None = None) -> LlmProvider:
        if kind is not ProviderKind.VLLM:
            raise AssertionError("unexpected provider")
        if endpoint_alias != "general-dev-gpu":
            raise AssertionError("unexpected endpoint alias")
        return cast(LlmProvider, FakeProvider())


class FakeRuntime:
    providers = FakeRegistry()


def _model_config(capability: str, config_id: int) -> AiModelConfig:
    return AiModelConfig(
        id=config_id,
        brokerage_id=1,
        capability=capability,
        config_key=f"{capability.lower()}-default",
        config_version=1,
        provider="vllm",
        model_name="prototype-model",
        endpoint_alias="general-dev-gpu",
    )


def test_db_model_routes_enforce_provider_endpoint_contract() -> None:
    openai = AiModelConfig(
        brokerage_id=1,
        capability="POSITION_CARD",
        config_key="local-openai",
        config_version=1,
        provider="openai",
        model_name="gpt-5.6-luna",
    )
    llama_cpp = AiModelConfig(
        brokerage_id=1,
        capability="POSITION_CARD",
        config_key="dev-llama",
        config_version=1,
        provider="llama_cpp",
        model_name="qwen-gguf",
        endpoint_alias="general-dev-gpu",
    )
    bedrock = AiModelConfig(
        brokerage_id=1,
        capability="BROKERAGE_JUDGMENT",
        config_key="dev-bedrock-gpt56-luna",
        config_version=1,
        provider="bedrock",
        model_name="global.openai.gpt-5.6-luna",
        endpoint_alias="general-dev-bedrock",
    )

    assert _route(openai).endpoint_alias is None
    assert _route(llama_cpp).provider is ProviderKind.LLAMA_CPP
    assert _route(llama_cpp).endpoint_alias == "general-dev-gpu"
    assert _route(bedrock).provider is ProviderKind.BEDROCK
    assert _route(bedrock).endpoint_alias == "general-dev-bedrock"

    with pytest.raises(ConfigurationError, match="vllm route requires"):
        _route(
            AiModelConfig(
                brokerage_id=1,
                capability="POSITION_CARD",
                config_key="invalid-vllm",
                config_version=1,
                provider="vllm",
                model_name="qwen-bnb",
            )
        )
    with pytest.raises(ConfigurationError, match="openai route cannot have"):
        _route(openai.model_copy(update={"endpoint_alias": "general-dev-gpu"}))
    with pytest.raises(ConfigurationError, match="llama_cpp route requires"):
        _route(llama_cpp.model_copy(update={"endpoint_alias": None}))
    with pytest.raises(ConfigurationError, match="bedrock route requires"):
        _route(bedrock.model_copy(update={"endpoint_alias": "  "}))
    with pytest.raises(ConfigurationError, match="provider is not supported"):
        _route(bedrock.model_copy(update={"provider": "unknown-provider"}))


def test_bindings_use_separate_capabilities_and_explicit_synthetic_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import f3_runtime

    configs = {
        "POSITION_CARD": _model_config("POSITION_CARD", 7),
        "BROKERAGE_JUDGMENT": _model_config("BROKERAGE_JUDGMENT", 9),
    }
    monkeypatch.setattr(
        f3_runtime.repository,
        "find_active_model_config",
        lambda _session, _brokerage_id, capability: configs[capability],
    )

    card_bindings = build_bindings(
        cast(Session, object()),
        cast(AiRuntime, FakeRuntime()),
        AgentRun(
            brokerage_id=1,
            run_group_id="018f7c9e-0f2f-7c1e-9a3b-2f7c9e0f2f7c",  # type: ignore[arg-type]
            run_type="CROSS_JUDGMENT",
            agent_type="BROKERAGE_WORKFLOW",
            status="RUNNING",
            trigger_type="USER_REQUEST",
            requested_by=1,
        ),
    )
    monkeypatch.setattr(f3_runtime, "_judgment_required", lambda *_args: True)
    judgment_bindings = build_bindings(
        cast(Session, object()),
        cast(AiRuntime, FakeRuntime()),
        AgentRun(
            brokerage_id=1,
            run_group_id="018f7c9e-0f2f-7c1e-9a3b-2f7c9e0f2f7c",  # type: ignore[arg-type]
            run_type="CROSS_JUDGMENT",
            agent_type="BROKERAGE_WORKFLOW",
            status="CANDIDATE_CARDS_READY",
            trigger_type="USER_REQUEST",
            requested_by=1,
        ),
    )

    assert card_bindings.card is not None
    assert card_bindings.card.model_config_id == 7
    assert card_bindings.judgment is None
    assert card_bindings.card.input_privacy_mode is InputPrivacyMode.SYNTHETIC_PROTOTYPE
    assert judgment_bindings.card is None
    assert judgment_bindings.judgment is not None
    assert judgment_bindings.judgment.model_config_id == 9
    assert judgment_bindings.judgment.input_privacy_mode is InputPrivacyMode.SYNTHETIC_PROTOTYPE


def test_zero_candidates_do_not_look_up_a_judgment_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import f3_runtime

    monkeypatch.setattr(f3_runtime, "_judgment_required", lambda *_args: False)
    monkeypatch.setattr(
        f3_runtime.repository,
        "find_active_model_config",
        lambda *_args: (_ for _ in ()).throw(AssertionError("model config must not be read")),
    )
    run = AgentRun(
        brokerage_id=1,
        run_group_id="018f7c9e-0f2f-7c1e-9a3b-2f7c9e0f2f7c",  # type: ignore[arg-type]
        run_type="CROSS_JUDGMENT",
        agent_type="BROKERAGE_WORKFLOW",
        status="CANDIDATE_CARDS_READY",
        trigger_type="USER_REQUEST",
        requested_by=1,
    )

    bindings = build_bindings(cast(Session, object()), cast(AiRuntime, FakeRuntime()), run)

    assert bindings.card is None
    assert bindings.judgment is None


@pytest.mark.parametrize("status", ["ANCHOR_READY", "QUEUED", "COMPLETED", "CANCELLED", "unknown"])
def test_non_model_steps_do_not_resolve_providers_or_read_model_config(status: str) -> None:
    # No session/provider methods exist: accidentally resolving either fails immediately.
    run = AgentRun(
        brokerage_id=1,
        run_group_id="018f7c9e-0f2f-7c1e-9a3b-2f7c9e0f2f7c",  # type: ignore[arg-type]
        run_type="CROSS_JUDGMENT",
        agent_type="BROKERAGE_WORKFLOW",
        status=status,
        trigger_type="USER_REQUEST",
        requested_by=1,
    )

    bindings = build_bindings(cast(Session, object()), cast(AiRuntime, object()), run)

    assert bindings.card is None
    assert bindings.judgment is None
