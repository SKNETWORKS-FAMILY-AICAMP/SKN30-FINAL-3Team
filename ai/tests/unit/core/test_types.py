import pytest
from pydantic import ValidationError

from brokerage_ai.core.types import ModelRoute, ProviderKind


def test_model_route_normalizes_endpoint_alias() -> None:
    route = ModelRoute(
        provider=ProviderKind.LLAMA_CPP,
        model="  qwen-gguf  ",
        endpoint_alias="  general-dev-gpu  ",
    )

    assert route.model == "qwen-gguf"
    assert route.endpoint_alias == "general-dev-gpu"


def test_openai_route_rejects_endpoint_alias() -> None:
    with pytest.raises(ValidationError, match="must not use endpoint_alias"):
        ModelRoute(
            provider=ProviderKind.OPENAI,
            model="gpt-4o-mini",
            endpoint_alias="general-dev-gpu",
        )


def test_llama_cpp_route_requires_endpoint_alias() -> None:
    with pytest.raises(ValidationError, match="require endpoint_alias"):
        ModelRoute(provider=ProviderKind.LLAMA_CPP, model="qwen-gguf")


def test_bedrock_route_requires_endpoint_alias() -> None:
    with pytest.raises(ValidationError, match="bedrock routes require endpoint_alias"):
        ModelRoute(provider=ProviderKind.BEDROCK, model="global.openai.gpt-5.6-luna")


def test_bedrock_route_accepts_normalized_endpoint_alias() -> None:
    route = ModelRoute(
        provider=ProviderKind.BEDROCK,
        model="global.openai.gpt-5.6-luna",
        endpoint_alias=" general-dev-bedrock ",
    )

    assert route.endpoint_alias == "general-dev-bedrock"


def test_vllm_route_keeps_unaliased_f2_compatibility() -> None:
    route = ModelRoute(provider=ProviderKind.VLLM, model="sllm")

    assert route.endpoint_alias is None
