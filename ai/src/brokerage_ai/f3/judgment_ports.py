"""F3 중개 판정 생성의 공개 경계."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from brokerage_ai.f3.judgment_contracts import (
    BrokerageJudgmentRequest,
    BrokerageJudgmentResult,
)


class BrokerageJudgmentGeneratorVersions(BaseModel):
    """생성 전에 알 수 있어야 하는 버전.

    Backend 가 실행에 바인딩을 기록할 때 모델을 부르기 전에 필요하다. Provider SDK 객체나
    DB 의 `model_config_id` 는 여기에 담지 않는다.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt_version: str = Field(min_length=1)
    workflow_version: str = Field(min_length=1)


class BrokerageJudgmentGenerator(Protocol):
    """앵커 1장 + 후보 N장을 한 번에 판정하는 유일한 공개 진입점.

    구현은 프롬프트, 모델 호출과 오케스트레이션을 소유한다. Backend 는 이 Protocol 만 보고,
    DB 저장은 호출한 Backend 쪽에서 한다. 이 호출 자체에는 저장 부수 효과가 없다.
    """

    @property
    def versions(self) -> BrokerageJudgmentGeneratorVersions: ...

    async def judge_candidates(
        self, request: BrokerageJudgmentRequest
    ) -> BrokerageJudgmentResult: ...
