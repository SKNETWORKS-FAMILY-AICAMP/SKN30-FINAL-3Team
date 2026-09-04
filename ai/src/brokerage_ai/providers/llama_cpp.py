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
    ProviderDiagnostics,
    ProviderKind,
    StructuredGenerationRequest,
    StructuredGenerationResult,
    TokenUsage,
)

OutputT = TypeVar("OutputT", bound=BaseModel)


class LlamaCppAdapter:
    """llama.cpp의 OpenAI-compatible Chat Completions 구조화 생성 어댑터."""

    def __init__(self, client: AsyncOpenAI) -> None:
        self._client = client

    @property
    def kind(self) -> ProviderKind:
        return ProviderKind.LLAMA_CPP

    async def generate_structured(
        self,
        request: StructuredGenerationRequest,
        output_schema: type[OutputT],
    ) -> StructuredGenerationResult[OutputT]:
        if request.route.provider is not self.kind:
            raise ProviderConfigurationError(
                f"{self.kind.value} adapter cannot handle {request.route.provider.value} route"
            )

        parameters: dict[str, Any] = {
            "model": request.route.model,
            "messages": [
                {"role": message.role.value, "content": message.content}
                for message in request.messages
            ],
            # llama.cpp는 OpenAI의 json_schema wrapper가 아니라 schema를 response_format
            # 바로 아래에서 받는다. 반환 문자열은 아래에서 Pydantic으로 다시 검증한다.
            "response_format": {
                "type": "json_schema",
                "schema": output_schema.model_json_schema(),
            },
        }
        if request.temperature is not None:
            parameters["temperature"] = request.temperature
        if request.max_output_tokens is not None:
            parameters["max_tokens"] = request.max_output_tokens

        started_at = perf_counter()
        try:
            response = await self._client.chat.completions.create(**parameters)
        except OpenAIError as exc:
            raise translate_openai_error(exc) from None
        latency_ms = (perf_counter() - started_at) * 1000

        try:
            choices = response.choices
        except AttributeError:
            raise ProviderResponseError() from None
        if not choices:
            raise ProviderResponseError()
        try:
            message = choices[0].message
        except (AttributeError, IndexError, TypeError):
            raise ProviderResponseError() from None
        if getattr(message, "refusal", None):
            raise ProviderRefusalError()
        try:
            content = message.content
        except AttributeError:
            raise ProviderResponseError() from None
        if not isinstance(content, str) or not content.strip():
            raise ProviderOutputInvalidError("response has no JSON content")
        try:
            parsed = output_schema.model_validate_json(content)
        except ValidationError as exc:
            raise ProviderOutputInvalidError(describe_validation_error(exc)) from exc

        try:
            usage = getattr(response, "usage", None)
            token_usage = (
                TokenUsage(
                    input_tokens=usage.prompt_tokens,
                    output_tokens=usage.completion_tokens,
                    total_tokens=usage.total_tokens,
                )
                if usage is not None
                else None
            )
            diagnostics = ProviderDiagnostics(
                provider=self.kind,
                model=response.model,
                request_id=response.id,
                latency_ms=latency_ms,
                usage=token_usage,
            )
        except (AttributeError, TypeError, ValidationError):
            raise ProviderResponseError() from None
        return StructuredGenerationResult[OutputT](
            output=parsed,
            diagnostics=diagnostics,
        )
