from __future__ import annotations

from time import perf_counter
from typing import Any, TypeVar

from openai import AsyncOpenAI, OpenAIError
from pydantic import BaseModel, ValidationError

from brokerage_ai.core.errors import (
    ProviderConfigurationError,
    ProviderOutputInvalidError,
    ProviderRefusalError,
    ProviderResponseError,
    describe_validation_error,
    translate_openai_error,
)
from brokerage_ai.core.types import (
    EmbeddingRequest,
    EmbeddingResult,
    ProviderDiagnostics,
    ProviderKind,
    StructuredGenerationRequest,
    StructuredGenerationResult,
    TokenUsage,
)

OutputT = TypeVar("OutputT", bound=BaseModel)


class VllmAdapter:
    def __init__(
        self,
        *,
        llm_client: AsyncOpenAI | None,
        embedding_client: AsyncOpenAI | None,
    ) -> None:
        self._llm_client = llm_client
        self._embedding_client = embedding_client

    @property
    def kind(self) -> ProviderKind:
        return ProviderKind.VLLM

    @property
    def supports_llm(self) -> bool:
        return self._llm_client is not None

    @property
    def supports_embedding(self) -> bool:
        return self._embedding_client is not None

    async def generate_structured(
        self,
        request: StructuredGenerationRequest,
        output_schema: type[OutputT],
    ) -> StructuredGenerationResult[OutputT]:
        self._validate_route(request.route.provider)
        if self._llm_client is None:
            raise ProviderConfigurationError("vllm LLM endpoint is not configured")

        parameters: dict[str, Any] = {
            "model": request.route.model,
            "messages": [
                {"role": message.role.value, "content": message.content}
                for message in request.messages
            ],
            "response_format": output_schema,
        }
        if request.temperature is not None:
            parameters["temperature"] = request.temperature
        if request.max_output_tokens is not None:
            parameters["max_tokens"] = request.max_output_tokens

        started_at = perf_counter()
        try:
            response = await self._llm_client.chat.completions.parse(**parameters)
        except OpenAIError as exc:
            raise translate_openai_error(exc) from None
        except ValidationError as exc:
            # 모델이 계약을 어긴 출력이다. OpenAI adapter와 같은 등급으로 다룬다.
            raise ProviderOutputInvalidError(describe_validation_error(exc)) from exc
        except ValueError as exc:
            raise ProviderOutputInvalidError() from exc
        latency_ms = (perf_counter() - started_at) * 1000

        if not response.choices:
            raise ProviderResponseError()
        message = response.choices[0].message
        if message.refusal:
            raise ProviderRefusalError()
        parsed = message.parsed
        if parsed is None:
            # 본문을 못 읽었다. 잘린 응답이 여기로 오며 다시 부르면 통과할 수 있다.
            raise ProviderOutputInvalidError("response has no parsed output")
        if not isinstance(parsed, output_schema):
            # 선언한 schema와 다른 타입이다. 다시 불러도 같으므로 재시도하지 않는다.
            raise ProviderResponseError()

        usage = response.usage
        token_usage = (
            TokenUsage(
                input_tokens=usage.prompt_tokens,
                output_tokens=usage.completion_tokens,
                total_tokens=usage.total_tokens,
            )
            if usage is not None
            else None
        )
        return StructuredGenerationResult[OutputT](
            output=parsed,
            diagnostics=ProviderDiagnostics(
                provider=self.kind,
                model=response.model,
                request_id=response.id,
                latency_ms=latency_ms,
                usage=token_usage,
            ),
        )

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        self._validate_route(request.route.provider)
        if self._embedding_client is None:
            raise ProviderConfigurationError("vllm embedding endpoint is not configured")

        parameters: dict[str, Any] = {
            "model": request.route.model,
            "input": list(request.inputs),
            "encoding_format": "float",
        }
        if request.dimensions is not None:
            parameters["dimensions"] = request.dimensions

        started_at = perf_counter()
        try:
            response = await self._embedding_client.embeddings.create(**parameters)
        except OpenAIError as exc:
            raise translate_openai_error(exc) from None
        latency_ms = (perf_counter() - started_at) * 1000

        vectors = self._ordered_vectors(response.data, len(request.inputs))
        return EmbeddingResult(
            vectors=vectors,
            diagnostics=ProviderDiagnostics(
                provider=self.kind,
                model=response.model,
                latency_ms=latency_ms,
                usage=TokenUsage(
                    input_tokens=response.usage.prompt_tokens,
                    total_tokens=response.usage.total_tokens,
                ),
            ),
        )

    def _validate_route(self, provider: ProviderKind) -> None:
        if provider is not self.kind:
            raise ProviderConfigurationError(
                f"{self.kind.value} adapter cannot handle {provider.value} route"
            )

    @staticmethod
    def _ordered_vectors(data: list[Any], expected_count: int) -> tuple[tuple[float, ...], ...]:
        ordered = sorted(data, key=lambda item: item.index)
        if [item.index for item in ordered] != list(range(expected_count)):
            raise ProviderResponseError("provider returned invalid embedding indices")
        vectors = tuple(tuple(float(value) for value in item.embedding) for item in ordered)
        if not vectors or any(not vector for vector in vectors):
            raise ProviderResponseError("provider returned an empty embedding")
        dimensions = {len(vector) for vector in vectors}
        if len(dimensions) != 1:
            raise ProviderResponseError("provider returned inconsistent embedding dimensions")
        return vectors
