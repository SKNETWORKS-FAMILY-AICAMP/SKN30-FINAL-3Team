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
