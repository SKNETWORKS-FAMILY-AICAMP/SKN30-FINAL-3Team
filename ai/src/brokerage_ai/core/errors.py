from __future__ import annotations

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    OpenAIError,
    RateLimitError,
)


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
