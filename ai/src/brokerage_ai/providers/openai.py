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


class OpenAIAdapter:
    def __init__(self, client: AsyncOpenAI) -> None:
        self._client = client

    @property
    def kind(self) -> ProviderKind:
        return ProviderKind.OPENAI

    async def generate_structured(
        self,
        request: StructuredGenerationRequest,
        output_schema: type[OutputT],
    ) -> StructuredGenerationResult[OutputT]:
        self._validate_route(request.route.provider)
        parameters: dict[str, Any] = {
            "model": request.route.model,
            "input": [
                {"role": message.role.value, "content": message.content}
                for message in request.messages
            ],
            "text_format": output_schema,
            "store": False,
        }
        if request.temperature is not None:
            parameters["temperature"] = request.temperature
        if request.max_output_tokens is not None:
            parameters["max_output_tokens"] = request.max_output_tokens

        started_at = perf_counter()
        try:
            response = await self._client.responses.parse(**parameters)
        except OpenAIError as exc:
            raise translate_openai_error(exc) from None
        except ValidationError as exc:
            # 모델이 계약을 어긴 출력을 냈다. 설정 오류가 아니라 다시 부르면 달라질 수 있는
            # 실패다. 원인을 `from None`으로 버리지 않는다. 버리면 무엇이 어긋났는지 알 방법이
            # 사라져 계측을 새로 붙이기 전에는 진단할 수 없다.
            raise ProviderOutputInvalidError(describe_validation_error(exc)) from exc
        except ValueError as exc:
            raise ProviderOutputInvalidError() from exc
        latency_ms = (perf_counter() - started_at) * 1000

        parsed = response.output_parsed
        if parsed is None:
            if self._contains_refusal(response.output):
                raise ProviderRefusalError()
            # 잘린 응답(`max_output_tokens` 초과)이 여기로 온다. 다시 부르면 통과할 수 있다.
            raise ProviderOutputInvalidError(_incomplete_reason(response))
        if not isinstance(parsed, output_schema):
            # 선언한 schema와 다른 타입이 돌아왔다. 다시 불러도 같으므로 재시도하지 않는다.
            raise ProviderResponseError()

        usage = response.usage
        token_usage = (
            TokenUsage(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                total_tokens=usage.total_tokens,
            )
            if usage is not None
            else None
        )
        return StructuredGenerationResult[OutputT](
            output=parsed,
            diagnostics=ProviderDiagnostics(
                provider=self.kind,
                model=str(response.model),
                request_id=response.id,
                latency_ms=latency_ms,
                usage=token_usage,
            ),
        )

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        self._validate_route(request.route.provider)
        parameters: dict[str, Any] = {
            "model": request.route.model,
            "input": list(request.inputs),
            "encoding_format": "float",
        }
        if request.dimensions is not None:
            parameters["dimensions"] = request.dimensions

        started_at = perf_counter()
        try:
            response = await self._client.embeddings.create(**parameters)
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
    def _contains_refusal(outputs: list[Any]) -> bool:
        return any(
            getattr(content, "type", None) == "refusal"
            for output in outputs
            for content in getattr(output, "content", ())
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


def _incomplete_reason(response: object) -> str:
    """왜 본문을 못 읽었는지. 모델이 만든 문장이 아니라 Provider의 종료 사유만 옮긴다."""
    details = getattr(response, "incomplete_details", None)
    reason = getattr(details, "reason", None)
    return f"response is incomplete: {reason}" if reason else "response has no parsed output"
