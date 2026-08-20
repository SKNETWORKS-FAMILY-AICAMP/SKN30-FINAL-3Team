"""F3 포지션 카드 생성의 공개 경계."""

from __future__ import annotations

from typing import Protocol

from brokerage_ai.f3.contracts import (
    PositionCardGenerationRequest,
    PositionCardGenerationResult,
)


class PositionCardGenerator(Protocol):
    """포지션 카드 1장을 만드는 유일한 공개 진입점.

    구현은 프롬프트, 모델 호출과 그래프를 소유한다. Backend는 이 Protocol 만 보고, DB 저장은
    호출한 Backend 쪽에서 한다. 이 호출 자체에는 저장 부수 효과가 없다.
    """

    async def generate_position_card(
        self, request: PositionCardGenerationRequest
    ) -> PositionCardGenerationResult: ...
