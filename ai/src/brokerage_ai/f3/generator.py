"""포지션 카드 생성 구현.

Provider 와 모델은 생성자로 주입받는다. 기본 Provider 나 기본 모델을 여기서 정하지 않으며
OpenAI·vLLM adapter 를 직접 분기하지도 않는다. 운영 선택은 호출 조립 지점의 책임이다
(AI-OQ-001~003 미확정).
"""

from __future__ import annotations

from brokerage_ai.core.types import (
    ModelRoute,
    StructuredGenerationRequest,
    StructuredGenerationResult,
)
from brokerage_ai.f3.contracts import (
    InputPrivacyMode,
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
from brokerage_ai.f3.validation import PositionCardContractError, validate_generation_result
from brokerage_ai.providers.ports import LlmProvider
from brokerage_ai.providers.repair import generate_with_repair

POSITION_CARD_WORKFLOW_VERSION = "position-card-workflow:v1"

# 같은 입력에서 같은 카드가 나와야 캐시와 재현성이 성립한다 (F3-NF-08).
POSITION_CARD_TEMPERATURE = 0.0


class LlmPositionCardGenerator:
    """구조화 출력 1회로 앵커 포지션 카드를 만든다.

    모델은 판단만 한다. 대상, source identity, 계약 버전과 장부 표기 금액은 요청에서
    결정적으로 복사하며 모델 출력 schema 에 아예 존재하지 않는다.

    `allow_synthetic_prototype`은 ADR-0014의 합성 케이스 실행을 조립 지점에서 명시하는
    임시 opt-in이다. 기본값은 false이며 실제 개인정보나 외부 Provider 전송을 승인하지 않는다.
    """

    def __init__(
        self,
        *,
        provider: LlmProvider,
        route: ModelRoute,
        allow_synthetic_prototype: bool = False,
    ) -> None:
        if provider.kind is not route.provider:
            raise ValueError("provider kind and model route provider must match")
        self._provider = provider
        self._route = route
        self._allow_synthetic_prototype = allow_synthetic_prototype

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
        if (
            request.input_privacy_mode is InputPrivacyMode.SYNTHETIC_PROTOTYPE
            and not self._allow_synthetic_prototype
        ):
            raise PositionCardContractError(
                "synthetic prototype input requires an explicit generator opt-in"
            )
        generation = StructuredGenerationRequest(
            route=self._route,
            messages=build_position_card_messages(request),
            temperature=POSITION_CARD_TEMPERATURE,
        )

        def finalize(
            produced: StructuredGenerationResult[PositionCardModelOutput],
        ) -> PositionCardGenerationResult:
            versions = self.versions
            result = PositionCardGenerationResult(
                target=PositionCardTarget.from_request(request),
                analysis=assemble_analysis(request, produced.output),
                prompt_version=versions.prompt_version,
                workflow_version=versions.workflow_version,
                diagnostics=produced.diagnostics,
            )
            validate_generation_result(request, result)
            return result

        # 조립과 대조까지 되먹임 범위에 넣는다. 없는 로그를 인용하거나 장부가 열지 않은 거래
        # 유형을 말한 것도 모델이 원인이며, 지적해 주면 고칠 수 있다.
        return await generate_with_repair(
            provider=self._provider,
            request=generation,
            output_schema=PositionCardModelOutput,
            finalize=finalize,
        )
