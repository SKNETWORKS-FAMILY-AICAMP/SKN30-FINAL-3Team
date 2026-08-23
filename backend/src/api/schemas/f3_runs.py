from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from domain.agent_execution.feedback import (
    DETAIL_MAX_LENGTH,
    FeedbackReason,
    FeedbackTarget,
    FeedbackType,
)
from domain.agent_execution.models import (
    LEASE_EXPIRED_FAILURE_CODE,
    LEASE_EXPIRED_FAILURE_MESSAGE,
    AgentRun,
    AiDecisionFeedback,
    AnchorType,
    anchor_of,
)
from domain.agent_execution.pipeline import SUPERSEDED_FAILURE_CODE, SUPERSEDED_FAILURE_MESSAGE
from domain.agent_execution.results import CandidateView, CardView, RunResult

# DB의 failure_message는 외부 AI 오류 원문·내부 예외·개인정보가 들어올 수 있는 내부 운영
# 정보다. 공개 응답은 원문을 쓰지 않고 아래 allowlist에 있는 코드만 고정 문구로 변환한다.
PUBLIC_FAILURE_MESSAGES = {
    LEASE_EXPIRED_FAILURE_CODE: LEASE_EXPIRED_FAILURE_MESSAGE,
    SUPERSEDED_FAILURE_CODE: SUPERSEDED_FAILURE_MESSAGE,
}
GENERIC_FAILURE_CODE = "EXECUTION_FAILED"
GENERIC_FAILURE_MESSAGE = "실행에 실패했습니다. 잠시 후 다시 시도해 주세요"


def public_failure(failure_code: str | None) -> tuple[str | None, str | None]:
    """저장된 실패 코드를 공개 가능한 코드·문구로 옮긴다. 모르는 코드는 일반화한다."""
    if failure_code is None:
        return None, None
    message = PUBLIC_FAILURE_MESSAGES.get(failure_code)
    if message is None:
        return GENERIC_FAILURE_CODE, GENERIC_FAILURE_MESSAGE
    return failure_code, message


class F3RunCreateRequest(BaseModel):
    """실행 요청은 앵커만 받는다. 사무소·요청자·상태는 서버가 정한다."""

    model_config = ConfigDict(extra="forbid")

    anchor_type: AnchorType
    anchor_id: int = Field(ge=1)


class F3RunResponse(BaseModel):
    run_id: int
    run_group_id: UUID
    status: str
    anchor_type: AnchorType
    anchor_id: int
    input_data_version: int
    created_at: datetime | None

    @classmethod
    def from_domain(cls, run: AgentRun) -> F3RunResponse:
        """사무소 식별자, 요청자와 입력 스냅샷은 응답에 싣지 않는다."""
        anchor_type, anchor_id = anchor_of(run)
        return cls(
            run_id=run.id or 0,
            run_group_id=run.run_group_id,
            status=run.status,
            anchor_type=anchor_type,
            anchor_id=anchor_id,
            input_data_version=run.input_data_version,
            created_at=run.created_at,
        )


class F3RunStatusResponse(BaseModel):
    """polling용 상태 응답. 실행 식별자는 숫자 PK이고 run_group_id는 싣지 않는다."""

    run_id: int
    status: str
    anchor_type: AnchorType
    anchor_id: int
    input_data_version: int
    created_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    failure_code: str | None
    failure_message: str | None

    @classmethod
    def from_domain(cls, run: AgentRun) -> F3RunStatusResponse:
        """사무소·요청자·모델 설정과 입출력 스냅샷은 공개하지 않는다.

        DB의 failure_message 원문도 공개하지 않고 allowlist 변환 결과만 싣는다.
        """
        anchor_type, anchor_id = anchor_of(run)
        failure_code, failure_message = public_failure(run.failure_code)
        return cls(
            run_id=run.id or 0,
            status=run.status,
            anchor_type=anchor_type,
            anchor_id=anchor_id,
            input_data_version=run.input_data_version,
            created_at=run.created_at,
            started_at=run.started_at,
            completed_at=run.completed_at,
            failure_code=failure_code,
            failure_message=failure_message,
        )


class F3EvidenceResponse(BaseModel):
    """근거 1건. 인용이면 원문 위치로 이동할 수 있고 추정이면 설명만 있다 (F3-CR-14)."""

    field_name: str | None
    evidence_type: str
    interaction_id: int | None
    quote_text: str | None
    quote_start_offset: int | None
    quote_end_offset: int | None
    note: str | None
    evidence_side: str | None = None


class F3AnchorCardResponse(BaseModel):
    """앵커 포지션 카드. 계약 버전, 프롬프트·워크플로 버전과 모델 진단은 싣지 않는다."""

    position_analysis_id: int
    negotiation_side: str
    target_label: str | None
    generated_at: datetime | None
    analysis: dict[str, Any]
    evidence: list[F3EvidenceResponse]

    @classmethod
    def from_domain(cls, card: CardView) -> F3AnchorCardResponse:
        return cls(
            position_analysis_id=card.position_analysis_id,
            negotiation_side=card.negotiation_side,
            target_label=card.target_label,
            generated_at=card.generated_at,
            analysis=card.analysis,
            evidence=[
                F3EvidenceResponse(
                    field_name=item.field_name,
                    evidence_type=item.evidence_type,
                    interaction_id=item.interaction_id,
                    quote_text=item.quote_text,
                    quote_start_offset=item.quote_start_offset,
                    quote_end_offset=item.quote_end_offset,
                    note=item.note,
                )
                for item in card.evidence
            ],
        )


class F3CandidateResponse(BaseModel):
    """후보 1건. 판정 전이면 등급과 근거가 비어 있다.

    `CANDIDATES_READY` 까지는 SQL 후보이며 AI 등급이 아니다. 판정이 끝나기 전에 강함·약함·
    기각을 노출하지 않는다.
    """

    candidate_id: int
    rank: int
    selected_for_cards: bool
    sql_score: str | None
    price_amount: int | None
    received_at: str | None
    match_grade: str | None = None
    evaluation_basis: str | None = None
    primary_obstacle: str | None = None
    possible_concession: str | None = None
    recommended_action: dict[str, Any] | None = None
    exclusion_reason: str | None = None
    evidence: list[F3EvidenceResponse] = []

    @classmethod
    def from_domain(cls, view: CandidateView) -> F3CandidateResponse:
        judgment = view.judgment
        return cls(
            candidate_id=view.candidate_id,
            rank=view.rank,
            selected_for_cards=view.selected_for_cards,
            sql_score=view.score,
            price_amount=view.price_amount,
            received_at=view.received_at,
            match_grade=judgment.match_grade if judgment else None,
            evaluation_basis=judgment.evaluation_basis if judgment else None,
            primary_obstacle=judgment.primary_obstacle if judgment else None,
            possible_concession=judgment.possible_concession if judgment else None,
            recommended_action=(
                judgment.recommended_action if judgment and judgment.recommended_action else None
            ),
            # 기각도 사유와 함께 노출한다. 조용히 사라지는 후보를 만들지 않는다 (F3-BR-10).
            exclusion_reason=judgment.exclusion_reason if judgment else None,
            evidence=[
                F3EvidenceResponse(
                    field_name=item.field_name,
                    evidence_type=item.evidence_type,
                    interaction_id=item.interaction_id,
                    quote_text=item.quote_text,
                    quote_start_offset=item.quote_start_offset,
                    quote_end_offset=item.quote_end_offset,
                    note=item.note,
                    evidence_side=item.evidence_side,
                )
                for item in view.evidence
            ],
        )


class F3CandidateSelectionResponse(BaseModel):
    """후보 조회 조건과 건수. 후보가 0건이어도 조건은 그대로 보인다 (F3-CR-11)."""

    criteria: dict[str, Any] | None
    total_count: int
    carded_count: int
    remaining_count: int


class F3RunResultResponse(BaseModel):
    """실행 하나의 현재 결과.

    싣지 않는 것: 사무소 식별자, 요청자, 모델 설정과 스냅샷, 프롬프트·워크플로 버전, 실행
    입출력 스냅샷 원본, 토큰 수, `run_group_id`, `parent_run_id`, lease 세 값, 내부 실패 원문.
    """

    run_id: int
    status: str
    anchor_type: AnchorType
    anchor_id: int
    input_data_version: int
    created_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    failure_code: str | None
    failure_message: str | None
    anchor_card: F3AnchorCardResponse | None
    candidate_selection: F3CandidateSelectionResponse
    candidates: list[F3CandidateResponse]
    candidates_total: int
    limit: int
    offset: int

    @classmethod
    def from_domain(cls, result: RunResult) -> F3RunResultResponse:
        run = result.run
        anchor_type, anchor_id = anchor_of(run)
        failure_code, failure_message = public_failure(run.failure_code)
        return cls(
            run_id=run.id or 0,
            status=run.status,
            anchor_type=anchor_type,
            anchor_id=anchor_id,
            input_data_version=run.input_data_version,
            created_at=run.created_at,
            started_at=run.started_at,
            completed_at=run.completed_at,
            failure_code=failure_code,
            failure_message=failure_message,
            anchor_card=(
                F3AnchorCardResponse.from_domain(result.anchor_card) if result.anchor_card else None
            ),
            candidate_selection=F3CandidateSelectionResponse(
                criteria=result.criteria,
                total_count=result.total_count,
                carded_count=result.carded_count,
                remaining_count=result.remaining_count,
            ),
            candidates=[F3CandidateResponse.from_domain(view) for view in result.candidates.items],
            candidates_total=result.candidates.total,
            limit=result.candidates.limit,
            offset=result.candidates.offset,
        )


class F3FeedbackCreateRequest(BaseModel):
    """피드백 요청. 사무소와 작성자는 세션에서만 도출하므로 본문에 없다."""

    model_config = ConfigDict(extra="forbid")

    target: FeedbackTarget
    target_id: int = Field(ge=1)
    feedback_type: FeedbackType
    reason: FeedbackReason
    field_name: str | None = Field(default=None, max_length=100)
    corrected_value: dict[str, Any] | None = None
    detail: str | None = Field(default=None, max_length=DETAIL_MAX_LENGTH)


class F3FeedbackResponse(BaseModel):
    feedback_id: int
    target: FeedbackTarget
    target_id: int
    feedback_type: str
    reason: str
    created_at: datetime | None

    @classmethod
    def from_domain(cls, stored: AiDecisionFeedback) -> F3FeedbackResponse:
        """작성자와 사무소는 응답에 싣지 않는다."""
        target = (
            FeedbackTarget.POSITION_ANALYSIS
            if stored.position_analysis_id is not None
            else FeedbackTarget.MATCH_CANDIDATE
        )
        return cls(
            feedback_id=stored.id or 0,
            target=target,
            target_id=stored.position_analysis_id or stored.match_candidate_evaluation_id or 0,
            feedback_type=stored.feedback_type,
            reason=stored.reason,
            created_at=stored.created_at,
        )
