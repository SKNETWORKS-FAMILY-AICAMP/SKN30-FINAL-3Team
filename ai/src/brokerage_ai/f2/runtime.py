from __future__ import annotations

from collections.abc import Callable

from openai import OpenAI

from brokerage_ai.core.config import AiConfig, ProviderEndpointConfig
from brokerage_ai.core.errors import ProviderConfigurationError
from brokerage_ai.core.types import ModelRoute, ProviderKind
from brokerage_ai.f2.analyzer import LlmConsultationAnalyzer
from brokerage_ai.f2.pipeline import F2Pipeline
from brokerage_ai.f2.stt import VllmWhisperTranscriber
from brokerage_ai.runtime import AiRuntime, create_ai_runtime

SyncClientFactory = Callable[..., OpenAI]


class F2Runtime:
    """F2 파이프라인과 그 파이프라인이 소유한 Provider client 수명주기."""

    def __init__(
        self,
        *,
        pipeline: F2Pipeline,
        ai_runtime: AiRuntime,
        stt_client: OpenAI,
    ) -> None:
        self.pipeline = pipeline
        self._ai_runtime = ai_runtime
        self._stt_client = stt_client
        self._closed = False

    async def close(self) -> None:
        if self._closed:
            return
        try:
            self._stt_client.close()
        finally:
            await self._ai_runtime.close()
            self._closed = True


def _client_options(config: AiConfig, endpoint: ProviderEndpointConfig) -> dict[str, object]:
    return {
        "api_key": (
            endpoint.api_key.get_secret_value() if endpoint.api_key is not None else "not-required"
        ),
        "base_url": str(endpoint.base_url),
        "timeout": config.request_timeout_seconds,
        "max_retries": 0,
    }


def create_f2_runtime(
    config: AiConfig,
    *,
    sync_client_factory: SyncClientFactory = OpenAI,
) -> F2Runtime:
    if config.vllm.llm is None:
        raise ProviderConfigurationError("F2 requires AI_VLLM_LLM_BASE_URL")
    if config.vllm.stt is None:
        raise ProviderConfigurationError("F2 requires AI_VLLM_STT_BASE_URL")

    stt_client = sync_client_factory(**_client_options(config, config.vllm.stt))
    try:
        ai_runtime = create_ai_runtime(config)
        llm_provider = ai_runtime.providers.get_llm(ProviderKind.VLLM)
        pipeline = F2Pipeline(
            transcriber=VllmWhisperTranscriber(
                stt_client,
                model_id=config.f2.stt_model,
                language=config.f2.stt_language,
            ),
            analyzer=LlmConsultationAnalyzer(
                provider=llm_provider,
                route=ModelRoute(provider=ProviderKind.VLLM, model=config.f2.llm_model),
            ),
        )
        return F2Runtime(
            pipeline=pipeline,
            ai_runtime=ai_runtime,
            stt_client=stt_client,
        )
    except Exception:
        stt_client.close()
        raise
