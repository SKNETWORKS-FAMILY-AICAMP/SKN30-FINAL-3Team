"""AI 런타임 조립 지점.

Backend 는 `brokerage_ai` 의 공개 표면만 만진다 — Provider SDK 도 프롬프트도 여기 없다
(`tests/architecture/test_ai_dependency.py` 가 `openai`·`langgraph` import 를 막는다).
설정은 `ai/` 가 자기 `.env` 에서 읽으므로 Backend 설정에 모델 키를 복제하지 않는다.
"""

from __future__ import annotations

from brokerage_ai import (
    AiError,
    AiRuntime,
    ProviderError,
    create_ai_runtime,
    load_ai_config,
)
from brokerage_ai.providers.registry import ProviderRegistry
from fastapi import Request

from core.config import Config
from core.errors import ApplicationError


class AiUnavailableError(ApplicationError):
    """AI 설정이 없거나 Provider 를 만들 수 없는 상태. F3 는 죽어도 F1 은 살아야 한다."""

    status_code = 503

    def __init__(self, message: str = "ai runtime is not configured") -> None:
        super().__init__("AI_UNAVAILABLE", message)


class AiResponseError(ApplicationError):
    """모델이 응답했지만 쓸 수 없는 상태. 재시도해도 같다."""

    status_code = 502

    def __init__(self, message: str = "ai provider returned an unusable response") -> None:
        super().__init__("AI_RESPONSE_INVALID", message)


def translate_ai_error(error: AiError) -> ApplicationError:
    """AI 패키지 오류를 공개 계약으로 옮긴다.

    Provider 종류나 모델 이름은 응답에 싣지 않는다 — 호출자가 알 필요가 없고, 설정이
    새는 통로가 된다. 재시도로 풀릴 수 있는 오류만 503 으로 구분한다.
    """
    if isinstance(error, ProviderError) and error.retryable:
        return AiUnavailableError("ai provider is temporarily unavailable")
    if isinstance(error, ProviderError):
        # 설정 누락(route 에 맞는 Provider 없음)도 여기로 온다.
        return AiUnavailableError()
    return AiResponseError()


def build_ai_runtime(config: Config) -> AiRuntime | None:
    """설정이 없으면 None 을 돌려준다. F3 만 못 쓰고 나머지 API 는 정상 기동한다 (수용 기준 15).

    profile 은 Backend 환경을 그대로 넘긴다. `ai/` 가 자기 `.env.<profile>` 과 `.env` 를
    읽으므로 모델 비밀값이 Backend 설정에 복제되지 않는다.
    """
    try:
        ai_config = load_ai_config(config.app.environment.value)
    except Exception:  # noqa: BLE001 - 기동을 막지 않는다. 사용 시점에 503으로 알린다.
        return None
    # Provider 가 하나도 설정되지 않았으면 런타임을 만들어도 쓸 수 없다.
    if ai_config.openai is None and ai_config.vllm.llm is None:
        return None
    try:
        return create_ai_runtime(ai_config)
    except Exception:  # noqa: BLE001
        return None


def get_provider_registry(request: Request) -> ProviderRegistry:
    runtime: AiRuntime | None = getattr(request.app.state, "ai_runtime", None)
    if runtime is None:
        raise AiUnavailableError()
    return runtime.providers
