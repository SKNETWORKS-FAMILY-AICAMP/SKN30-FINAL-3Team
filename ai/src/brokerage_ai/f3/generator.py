"""포지션 카드 생성 구현.

Provider 와 모델은 생성자로 주입받는다. 기본 Provider 나 기본 모델을 여기서 정하지 않으며
OpenAI·vLLM adapter 를 직접 분기하지도 않는다. 운영 선택은 호출 조립 지점의 책임이다
(AI-OQ-001~003 미확정).
"""

from __future__ import annotations

from brokerage_ai.core.types import ModelRoute, StructuredGenerationRequest
from brokerage_ai.f3.contracts import (
    PositionCardGenerationRequest,
    PositionCardGenerationResult,
    PositionCardTarget,
)
from brokerage_ai.f3.model_output import PositionCardModelOutput, assemble_analysis
from brokerage_ai.f3.ports import PositionCardGeneratorVersions
from brokerage_ai.f3.prompts import (
    POSITION_CARD_PROMPT_VERSION,
    build_position_card_messages,
)
from brokerage_ai.providers.ports import LlmProvider

POSITION_CARD_WORKFLOW_VERSION = "position-card-workflow:v1"

# 같은 입력에서 같은 카드가 나와야 캐시와 재현성이 성립한다 (F3-NF-08).
POSITION_CARD_TEMPERATURE = 0.0


class LlmPositionCardGenerator:
    """구조화 출력 1회로 앵커 포지션 카드를 만든다.

    모델은 판단만 한다. 대상, source identity, 계약 버전과 장부 표기 금액은 요청에서
    결정적으로 복사하며 모델 출력 schema 에 아예 존재하지 않는다.
    """

    def __init__(self, *, provider: LlmProvider, route: ModelRoute) -> None:
        if provider.kind is not route.provider:
            raise ValueError("provider kind and model route provider must match")
        self._provider = provider
        self._route = route

    @property
    def versions(self) -> PositionCardGeneratorVersions:
        """Backend 가 cache key 를 계산하기 전에 알아야 하는 값."""
        return PositionCardGeneratorVersions(
            prompt_version=POSITION_CARD_PROMPT_VERSION,
            workflow_version=POSITION_CARD_WORKFLOW_VERSION,
        )

    async def generate_position_card(
        self, request: PositionCardGenerationRequest
    ) -> PositionCardGenerationResult:
        generation = StructuredGenerationRequest(
            route=self._route,
            messages=build_position_card_messages(request),
            temperature=POSITION_CARD_TEMPERATURE,
        )
        produced = await self._provider.generate_structured(generation, PositionCardModelOutput)
        versions = self.versions
        return PositionCardGenerationResult(
            target=PositionCardTarget.from_request(request),
            analysis=assemble_analysis(request, produced.output),
            prompt_version=versions.prompt_version,
            workflow_version=versions.workflow_version,
            diagnostics=produced.diagnostics,
        )
