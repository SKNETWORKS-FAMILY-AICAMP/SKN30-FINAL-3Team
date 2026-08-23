"""중개 판정 생성 구현.

Provider 와 모델은 생성자로 주입받는다. 기본 Provider 나 기본 모델을 여기서 정하지 않으며
OpenAI·vLLM adapter 를 직접 분기하지도 않는다. 운영 선택은 호출 조립 지점의 책임이다
(AI-OQ-001~003 미확정).

## LangGraph 를 쓰지 않는 이유

[AI ADR-0002](../../../../.agents/skills/ai/references/decisions/ADR-0002-langgraph-adoption.md)
는 F3 workflow 의 상태 전이·재개 기반으로 LangGraph 를 채택했다. 중개 판정 자체는 **구조화
출력 1회**다 (F3-NF-04). 노드가 하나뿐인 graph 는 상태 전이도 재개 지점도 만들지 않고 이름만
LangGraph 인 wrapper 가 된다.

현재 F3 의 단계 경계(`ANCHOR_READY` → `CANDIDATES_READY` → `CANDIDATE_CARDS_READY` →
`JUDGING` → `COMPLETED`)와 재개는 **Backend DB 상태**가 담당한다. Worker 가 저장된 상태를
보고 이어서 처리하므로 프로세스가 죽어도 진행이 남는다. LangGraph checkpointer 는 아직
쓰지 않으며 checkpoint 저장소 제품도 확정되지 않았다 (AI ADR-0002).

graph 가 실제로 필요해지는 시점은 한 번의 AI 호출 안에서 도구 호출·재질의·분기가 생길
때다. 그때 도입하고 `ai/` 안에 가둔다.
"""

from __future__ import annotations

from brokerage_ai.core.types import ModelRoute, StructuredGenerationRequest
from brokerage_ai.f3.judgment_contracts import (
    BrokerageJudgmentRequest,
    BrokerageJudgmentResult,
    BrokerageJudgmentTarget,
)
from brokerage_ai.f3.judgment_model_output import (
    BrokerageJudgmentModelOutput,
    assemble_candidates,
)
from brokerage_ai.f3.judgment_ports import BrokerageJudgmentGeneratorVersions
from brokerage_ai.f3.judgment_prompts import (
    BROKERAGE_JUDGMENT_PROMPT_VERSION,
    build_brokerage_judgment_messages,
)
from brokerage_ai.providers.ports import LlmProvider

BROKERAGE_JUDGMENT_WORKFLOW_VERSION = "brokerage-judgment-workflow:v1"

# 같은 카드 집합에서 같은 등급·기각이 나와야 재현성이 성립한다 (F3-NF-08).
BROKERAGE_JUDGMENT_TEMPERATURE = 0.0


class LlmBrokerageJudgmentGenerator:
    """앵커 1장 + 후보 N장을 **한 번의** 구조화 출력으로 판정한다.

    후보마다 개별 호출하지 않고 앵커를 후보 수만큼 반복 전송하지도 않는다
    (F3-BR-01, F3-BR-02, F3-NF-04). Provider SDK 응답은 공개 DTO 밖으로 나가지 않는다.
    """

    def __init__(self, *, provider: LlmProvider, route: ModelRoute) -> None:
        self._provider = provider
        self._route = route

    @property
    def versions(self) -> BrokerageJudgmentGeneratorVersions:
        """Backend 가 실행 바인딩을 기록하기 전에 알아야 하는 값."""
        return BrokerageJudgmentGeneratorVersions(
            prompt_version=BROKERAGE_JUDGMENT_PROMPT_VERSION,
            workflow_version=BROKERAGE_JUDGMENT_WORKFLOW_VERSION,
        )

    async def judge_candidates(self, request: BrokerageJudgmentRequest) -> BrokerageJudgmentResult:
        generation = StructuredGenerationRequest(
            route=self._route,
            messages=build_brokerage_judgment_messages(request),
            temperature=BROKERAGE_JUDGMENT_TEMPERATURE,
        )
        produced = await self._provider.generate_structured(
            generation, BrokerageJudgmentModelOutput
        )
        versions = self.versions
        return BrokerageJudgmentResult(
            # 대상은 모델이 아니라 요청에서 결정적으로 복사한다.
            target=BrokerageJudgmentTarget.from_request(request),
            candidates=assemble_candidates(request, produced.output),
            prompt_version=versions.prompt_version,
            workflow_version=versions.workflow_version,
            diagnostics=produced.diagnostics,
        )
