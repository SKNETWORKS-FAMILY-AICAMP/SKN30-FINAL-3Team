"""F3 포지션 카드 생성의 공개 경계."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from brokerage_ai.f3.contracts import (
    PositionCardGenerationRequest,
    PositionCardGenerationResult,
)


class PositionCardGeneratorVersions(BaseModel):
    """생성 전에 알 수 있어야 하는 버전.

    Backend 는 cache key 를 계산할 때 이 두 값이 필요한데, 그 시점은 아직 모델을 부르기
    전이다. Provider SDK 객체나 DB 의 `model_config_id` 는 여기에 담지 않는다.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt_version: str = Field(min_length=1)
    workflow_version: str = Field(min_length=1)


class PositionCardGenerator(Protocol):
    """포지션 카드 1장을 만드는 유일한 공개 진입점.

    구현은 프롬프트, 모델 호출과 그래프를 소유한다. Backend 는 이 Protocol 만 보고, DB 저장은
    호출한 Backend 쪽에서 한다. 이 호출 자체에는 저장 부수 효과가 없다.
    """

    @property
    def versions(self) -> PositionCardGeneratorVersions: ...

    async def generate_position_card(
        self, request: PositionCardGenerationRequest
    ) -> PositionCardGenerationResult: ...
