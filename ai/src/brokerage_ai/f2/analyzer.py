from __future__ import annotations

from brokerage_ai.core.types import (
    ChatMessage,
    MessageRole,
    ModelRoute,
    ProviderDiagnostics,
    StructuredGenerationRequest,
)
from brokerage_ai.f2.prompts import SYSTEM_PROMPT, build_user_prompt
from brokerage_ai.f2.types import ConsultationAnalysis, LedgerType
from brokerage_ai.providers.ports import LlmProvider


class LlmConsultationAnalyzer:
    """구조화 출력을 지원하는 로컬 LLM Provider로 F2 텍스트를 분석한다.

    ``route.model``만 바꾸면 Qwen3 후보나 QLoRA 결과물을 같은 파이프라인에서 사용할 수
    있다. 현재 저장소의 ``VllmAdapter``를 주입하면 로컬 vLLM의 Qwen을 호출한다.
    """

    def __init__(
        self,
        *,
        provider: LlmProvider,
        route: ModelRoute,
        max_output_tokens: int = 1024,
    ) -> None:
        if provider.kind is not route.provider:
            raise ValueError("provider kind and model route provider must match")
        self._provider = provider
        self._route = route
        self._max_output_tokens = max_output_tokens

    async def analyze(
        self,
        *,
        transcript: str,
        ledger_type: LedgerType,
    ) -> tuple[ConsultationAnalysis, ProviderDiagnostics]:
        request = StructuredGenerationRequest(
            route=self._route,
            messages=(
                ChatMessage(role=MessageRole.SYSTEM, content=SYSTEM_PROMPT),
                ChatMessage(
                    role=MessageRole.USER,
                    content=build_user_prompt(
                        transcript=transcript,
                        ledger_type=ledger_type,
                    ),
                ),
            ),
            temperature=0,
            max_output_tokens=self._max_output_tokens,
        )
        result = await self._provider.generate_structured(request, ConsultationAnalysis)
        return result.output, result.diagnostics
