"""되먹임 재생성 검증.

실제 Provider 도 네트워크도 쓰지 않는다. 대역이 무엇을 받았는지, 실패가 어떤 등급으로 나가는지,
되먹임 문구에 무엇이 담기는지만 본다.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, model_validator

from brokerage_ai.core.errors import (
    OutputContractError,
    ProviderOutputInvalidError,
    ProviderRateLimitError,
)
from brokerage_ai.core.types import (
    MessageRole,
    ProviderDiagnostics,
    ProviderKind,
    StructuredGenerationRequest,
    StructuredGenerationResult,
)
from brokerage_ai.providers.repair import REPAIR_MAX_ATTEMPTS, generate_with_repair
from conftest import Answer, generation_request

# 상담 원문을 흉내 낸 값. 되먹임 문구에 이런 것이 실리면 안 된다.
SECRET_LOG = "32억까지는 가능하다고 함. 010-****-**** 로 연락 요청."


class SampleContractError(OutputContractError):
    """기능 모듈이 자기 계약 오류를 이 조상 아래 두는 것을 흉내 낸다."""


class Strict(BaseModel):
    value: str

    @model_validator(mode="after")
    def value_must_not_be_empty(self) -> Strict:
        if not self.value:
            raise ValueError("value must not be empty")
        return self


def diagnostics() -> ProviderDiagnostics:
    return ProviderDiagnostics(provider=ProviderKind.OPENAI, model="test-model", latency_ms=1.0)


class ScriptedProvider:
    """호출마다 미리 정한 것을 내놓고 받은 요청을 전부 보관하는 대역."""

    def __init__(self, *outcomes: object) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[StructuredGenerationRequest] = []

    @property
    def kind(self) -> ProviderKind:
        return ProviderKind.OPENAI

    async def generate_structured(
        self, request: StructuredGenerationRequest, output_schema: type[Any]
    ) -> StructuredGenerationResult[Any]:
        self.calls.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return StructuredGenerationResult(output=Answer(value="ok"), diagnostics=diagnostics())


def request_with_a_log() -> StructuredGenerationRequest:
    """상담 원문이 실린 요청. 되먹임이 원문을 되풀이하지 않는지 보기 위한 입력이다."""
    base = generation_request(ProviderKind.OPENAI)
    messages = tuple(
        message.model_copy(update={"content": SECRET_LOG}) for message in base.messages
    )
    return base.model_copy(update={"messages": messages})


def repair_messages(request: StructuredGenerationRequest) -> list[str]:
    """원본 뒤에 덧붙은 되먹임 문구만."""
    return [message.content for message in request.messages[1:]]


@pytest.mark.asyncio
async def test_a_contract_violation_is_fed_back_and_the_next_attempt_succeeds() -> None:
    provider = ScriptedProvider(
        ProviderOutputInvalidError("timing: 마감일에는 근거가 필요하다"), None
    )

    result = await generate_with_repair(
        provider=provider,
        request=request_with_a_log(),
        output_schema=Answer,
        finalize=lambda produced: produced.output,
    )

    assert result == Answer(value="ok")
    assert len(provider.calls) == 2
    # 첫 시도는 원본 그대로다.
    assert provider.calls[0].messages == request_with_a_log().messages
    # 두 번째는 원본을 보존한 채 지적 한 건만 덧붙는다.
    assert provider.calls[1].messages[:1] == request_with_a_log().messages
    appended = repair_messages(provider.calls[1])
    assert len(appended) == 1
    assert "timing: 마감일에는 근거가 필요하다" in appended[0]
    assert appended[0].startswith("직전 응답이 계약 검증에 걸려 폐기됐다.")
    # 되먹임은 user 발화다. 모델이 하지 않은 말을 assistant 자리에 넣지 않는다.
    assert provider.calls[1].messages[-1].role is MessageRole.USER


@pytest.mark.asyncio
async def test_a_failure_raised_while_assembling_the_result_is_also_fed_back() -> None:
    """`finalize` 안의 실패가 되먹임 범위에 들어간다. 인용문 위조가 여기서 걸린다."""
    provider = ScriptedProvider(None, None)
    attempts: list[int] = []

    def finalize(produced: StructuredGenerationResult[Answer]) -> Answer:
        attempts.append(1)
        if len(attempts) == 1:
            raise SampleContractError("quote is not present in interaction 91")
        return produced.output

    result = await generate_with_repair(
        provider=provider,
        request=request_with_a_log(),
        output_schema=Answer,
        finalize=finalize,
    )

    assert result == Answer(value="ok")
    assert len(provider.calls) == 2
    assert "quote is not present in interaction 91" in repair_messages(provider.calls[1])[0]


@pytest.mark.asyncio
async def test_a_validation_error_is_fed_back_as_a_field_path_and_rule() -> None:
    provider = ScriptedProvider(None, None)
    attempts: list[int] = []

    def finalize(produced: StructuredGenerationResult[Answer]) -> Answer:
        attempts.append(1)
        if len(attempts) == 1:
            Strict(value="")
        return produced.output

    await generate_with_repair(
        provider=provider,
        request=request_with_a_log(),
        output_schema=Answer,
        finalize=finalize,
    )

    detail = repair_messages(provider.calls[1])[0]
    assert "value must not be empty" in detail
    # Pydantic 이 기본 문자열에 싣는 `input` 은 모델이 만든 값이라 담지 않는다.
    assert "input_value" not in detail


@pytest.mark.asyncio
async def test_feedback_does_not_accumulate_across_attempts() -> None:
    provider = ScriptedProvider(
        ProviderOutputInvalidError("첫 번째 지적"),
        ProviderOutputInvalidError("두 번째 지적"),
        None,
    )

    await generate_with_repair(
        provider=provider,
        request=request_with_a_log(),
        output_schema=Answer,
        finalize=lambda produced: produced.output,
    )

    assert len(provider.calls) == 3
    # 세 번째 시도도 원본 + 1건이다. 오래된 지적이 새 답을 흔들지 않는다.
    assert len(repair_messages(provider.calls[2])) == 1
    assert "두 번째 지적" in repair_messages(provider.calls[2])[0]
    assert "첫 번째 지적" not in repair_messages(provider.calls[2])[0]


@pytest.mark.asyncio
async def test_the_last_failure_keeps_its_type_when_attempts_run_out() -> None:
    """실패의 등급은 바뀌지 않는다. Backend 의 실행 수명주기 분류가 지금과 같아야 한다."""
    provider = ScriptedProvider(*[SampleContractError("고쳐지지 않는다")] * REPAIR_MAX_ATTEMPTS)

    with pytest.raises(SampleContractError, match="고쳐지지 않는다"):
        await generate_with_repair(
            provider=provider,
            request=request_with_a_log(),
            output_schema=Answer,
            finalize=lambda produced: produced.output,
        )

    assert len(provider.calls) == REPAIR_MAX_ATTEMPTS


@pytest.mark.asyncio
async def test_a_transport_failure_is_not_fed_back() -> None:
    """rate limit 은 모델에게 알려 줄 것이 없다. Worker 의 lease 재시도가 맡는다."""
    provider = ScriptedProvider(ProviderRateLimitError(), None)

    with pytest.raises(ProviderRateLimitError):
        await generate_with_repair(
            provider=provider,
            request=request_with_a_log(),
            output_schema=Answer,
            finalize=lambda produced: produced.output,
        )

    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_feedback_carries_no_consultation_content_or_model_output() -> None:
    """되먹임에 담기는 것은 필드 경로, 계약 문구와 식별자뿐이다."""
    provider = ScriptedProvider(
        ProviderOutputInvalidError("timing: hard_deadline requires at least one timing constraint"),
        None,
    )

    await generate_with_repair(
        provider=provider,
        request=request_with_a_log(),
        output_schema=Answer,
        finalize=lambda produced: produced.output,
    )

    appended = repair_messages(provider.calls[1])[0]
    assert SECRET_LOG not in appended
    assert "010" not in appended
    assert "32억" not in appended


@pytest.mark.asyncio
async def test_a_single_attempt_never_feeds_back() -> None:
    provider = ScriptedProvider(ProviderOutputInvalidError("지적"), None)

    with pytest.raises(ProviderOutputInvalidError):
        await generate_with_repair(
            provider=provider,
            request=request_with_a_log(),
            output_schema=Answer,
            finalize=lambda produced: produced.output,
            max_attempts=1,
        )

    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_a_non_positive_attempt_limit_is_rejected() -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        await generate_with_repair(
            provider=ScriptedProvider(),
            request=request_with_a_log(),
            output_schema=Answer,
            finalize=lambda produced: produced.output,
            max_attempts=0,
        )
