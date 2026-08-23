"""모델이 실제로 판단하는 값만 담는 내부 구조화 출력 schema.

모델 출력에서 서버 소유 필드를 **아예 뺀다.** `contract_version`, `target`, 앵커 카드 ID 와
후보 카드 ID 집합은 요청에서 결정적으로 복사한다. 여기 없는 값은 만들 수 없다.

이 모듈은 AI 내부 구현이며 Backend 공개 계약이 아니다.
"""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from brokerage_ai.f3.judgment_contracts import (
    TEXT_MAX_LENGTH,
    BrokerageJudgmentRequest,
    CandidateJudgment,
    JudgmentEvidence,
    MatchGrade,
    RecommendedAction,
)


class ModelCandidateJudgment(BaseModel):
    """후보 1건에 대한 모델의 판단만."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    card_id: int = Field(ge=1)
    grade: MatchGrade
    rank: int = Field(ge=1)
    comparison_basis: str = Field(min_length=1, max_length=TEXT_MAX_LENGTH)
    primary_obstacle: str | None = Field(default=None, max_length=TEXT_MAX_LENGTH)
    possible_concession: str | None = Field(default=None, max_length=TEXT_MAX_LENGTH)
    recommended_action: RecommendedAction | None = None
    rejection_reason: str | None = Field(default=None, max_length=TEXT_MAX_LENGTH)
    evidence: tuple[JudgmentEvidence, ...] = Field(min_length=1)


class BrokerageJudgmentModelOutput(BaseModel):
    """모델이 채우는 중개 판정.

    `contract_version`, `target`, `prompt_version`, `workflow_version`, `diagnostics` 와
    실행 제어 값은 이 schema 에 존재하지 않는다.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidates: tuple[ModelCandidateJudgment, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def each_candidate_appears_once(self) -> Self:
        identifiers = [candidate.card_id for candidate in self.candidates]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("candidates must not repeat a card_id")
        return self


def assemble_candidates(
    request: BrokerageJudgmentRequest, output: BrokerageJudgmentModelOutput
) -> tuple[CandidateJudgment, ...]:
    """모델 판단을 공개 결과로 옮긴다.

    순서만 요청 순서로 되돌린다. 등급·순위·근거를 여기서 고치거나 채워 넣지 않는다. 빠진
    후보와 늘어난 후보는 `validate_judgment_result()` 가 거절하며, 여기서 조용히 메우면 그
    검증이 무의미해진다.
    """
    judged = {candidate.card_id: candidate for candidate in output.candidates}
    ordered = [judged[card.card_id] for card in request.candidates if card.card_id in judged]
    # 요청에 없는 후보도 버리지 않고 그대로 싣는다. 검증이 문제를 드러내야 한다.
    ordered.extend(
        candidate
        for candidate in output.candidates
        if candidate.card_id not in {card.card_id for card in request.candidates}
    )
    return tuple(
        CandidateJudgment(
            card_id=candidate.card_id,
            grade=candidate.grade,
            rank=candidate.rank,
            comparison_basis=candidate.comparison_basis,
            primary_obstacle=candidate.primary_obstacle,
            possible_concession=candidate.possible_concession,
            recommended_action=candidate.recommended_action,
            rejection_reason=candidate.rejection_reason,
            evidence=candidate.evidence,
        )
        for candidate in ordered
    )
