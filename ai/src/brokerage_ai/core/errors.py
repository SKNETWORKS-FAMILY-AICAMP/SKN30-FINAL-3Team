from __future__ import annotations

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    OpenAIError,
    RateLimitError,
)
from pydantic import ValidationError


class AiError(Exception):
    """Base error exposed by the AI package."""


class ConfigurationError(AiError):
    """The supplied AI runtime configuration is invalid."""


class OutputContractError(AiError):
    """결과가 요청과 맞지 않는다. 모델을 다시 불러 고칠 수 있는 종류다.

    Pydantic 이 잡는 것은 결과 하나의 구조다. 이쪽은 그 결과가 **이 요청**에 대한 것이 맞는지를
    본 뒤에 나온다. 없는 상담 로그를 인용했거나, 마감일이 Backend 가 준 날짜 신호와 다르거나,
    장부가 열지 않은 거래 유형을 말한 경우다. 전부 모델이 만든 값이 원인이므로 무엇이 어긋났는지
    알려 주고 다시 부르면 고쳐질 수 있다.

    각 기능이 자기 오류 타입을 이 조상 아래 둔다. `core` 는 기능 모듈을 import 하지 않고도
    "되먹여 고칠 수 있는 계약 위반"을 한 덩어리로 잡을 수 있어야 한다.

    메시지에는 필드 이름, 우리가 계약에 적어 둔 고정 문구와 식별자만 담는다. 모델이 만든 값과
    상담 원문은 담지 않는다. 이 문구는 모델에게 되돌아가고 운영 로그로도 흘러간다.
    """


class ProviderError(AiError):
    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


class ProviderConfigurationError(ProviderError):
    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=False)


class ProviderTimeoutError(ProviderError):
    def __init__(self) -> None:
        super().__init__("provider request timed out", retryable=True)


class ProviderRateLimitError(ProviderError):
    def __init__(self) -> None:
        super().__init__("provider rate limit exceeded", retryable=True)


class ProviderUnavailableError(ProviderError):
    def __init__(self) -> None:
        super().__init__("provider is temporarily unavailable", retryable=True)


class ProviderRefusalError(ProviderError):
    def __init__(self) -> None:
        super().__init__("provider refused the structured request", retryable=False)


class ProviderResponseError(ProviderError):
    def __init__(self, message: str = "provider returned an invalid response") -> None:
        super().__init__(message, retryable=False)


class ProviderOutputInvalidError(ProviderError):
    """모델이 계약을 어긴 출력을 냈다. 다시 부르면 달라질 수 있다.

    구조화 출력의 교차 필드 규칙은 JSON schema로 표현할 수 없어 모델이 그 존재를 모른 채
    어길 수 있다. 프롬프트로 알려 주더라도 매번 지킨다는 보장은 없다. 같은 입력을 다시 부르면
    통과하는 종류의 실패이므로 설정 오류·인증 오류와 같은 등급으로 다루지 않는다.

    `ProviderResponseError`와 나눈 이유가 이것이다. 응답 자체를 해석할 수 없는 것(전송 계층이
    깨졌거나 schema가 잘못 선언된 것)은 다시 불러도 같으므로 재시도하지 않는다.

    `detail`에는 검증이 지적한 **필드 경로와 규칙 문구**만 담는다. 모델이 만든 값과 상담 원문은
    담지 않는다. 이 문구는 운영 로그로 흘러가며 공개 응답에는 쓰지 않는다.
    """

    def __init__(self, detail: str | None = None) -> None:
        message = "provider returned output that violates the contract"
        super().__init__(f"{message}: {detail}" if detail else message, retryable=True)
        # 되먹임 프롬프트에는 지적 내용만 넣는다. 고정 접두어까지 보내면 모델이 고쳐야 할 곳을
        # 찾는 대신 우리 오류 어휘를 읽는다.
        self.detail = detail


def describe_validation_error(error: ValidationError, limit: int = 3) -> str:
    """검증 실패를 진단 가능한 한 줄로 옮긴다.

    `loc`(필드 경로)와 `msg`(어긴 규칙)만 쓴다. Pydantic이 기본 문자열에 함께 싣는 `input`은
    **모델이 만든 값**이라 상담 내용이나 개인정보가 섞일 수 있으므로 담지 않는다. `msg`는
    우리가 계약에 적어 둔 규칙 문구이거나 Pydantic의 고정 문구다.

    여러 건이면 앞의 몇 개만 남긴다. 원인을 짚는 데는 충분하고 로그 한 줄이 보고서가 되지 않는다.
    """
    parts: list[str] = []
    for detail in error.errors()[:limit]:
        location = ".".join(str(entry) for entry in detail["loc"]) or "(root)"
        parts.append(f"{location}: {detail['msg']}")
    remaining = len(error.errors()) - len(parts)
    if remaining > 0:
        parts.append(f"(+{remaining} more)")
    return "; ".join(parts)


def translate_openai_error(error: OpenAIError) -> ProviderError:
    """Map SDK errors without copying request bodies, URLs, or credentials."""

    if isinstance(error, APITimeoutError):
        return ProviderTimeoutError()
    if isinstance(error, RateLimitError):
        return ProviderRateLimitError()
    if isinstance(error, APIConnectionError):
        return ProviderUnavailableError()
    if isinstance(error, APIStatusError):
        if error.status_code in {408, 409, 429} or error.status_code >= 500:
            return ProviderUnavailableError()
        return ProviderRefusalError()
    return ProviderResponseError()
