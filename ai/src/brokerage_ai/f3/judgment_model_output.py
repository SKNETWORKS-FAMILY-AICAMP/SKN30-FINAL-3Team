"""모델이 실제로 판단하는 값만 담는 내부 구조화 출력 schema.

모델 출력에서 서버 소유 필드와 카드에 이미 있는 근거 원문을 **아예 뺀다**. 모델은 짧은
근거 reference와 reason code를 고르고, 서버가 요청 카드의 검증된 근거와 공개 문구를
결정적으로 조립한다. 이 모듈은 AI 내부 구현이며 Backend 공개 계약이 아니다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from brokerage_ai.f3.contracts import Evidence, NegotiationSide
from brokerage_ai.f3.judgment_contracts import (
    BrokerageJudgmentRequest,
    CandidateJudgment,
    ContactChannel,
    JudgmentCard,
    JudgmentEvidence,
    MatchGrade,
    RecommendedAction,
)
from brokerage_ai.f3.judgment_validation import BrokerageJudgmentContractError

JUDGMENT_DETAIL_MAX_LENGTH = 120
JUDGMENT_ACTION_MAX_LENGTH = 120
JUDGMENT_MAX_EVIDENCE_REFS = 3


class ComparisonReason(StrEnum):
    PRICE_FIT = "PRICE_FIT"
    TIMING_FIT = "TIMING_FIT"
    CONDITION_FIT = "CONDITION_FIT"
    CONTACTABILITY_FIT = "CONTACTABILITY_FIT"
    OVERALL_FIT = "OVERALL_FIT"


class ObstacleReason(StrEnum):
    NONE = "NONE"
    PRICE_GAP = "PRICE_GAP"
    TIMING_MISMATCH = "TIMING_MISMATCH"
    CONDITION_CONFLICT = "CONDITION_CONFLICT"
    CONTACT_DIFFICULTY = "CONTACT_DIFFICULTY"
    DECISION_AUTHORITY = "DECISION_AUTHORITY"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    OTHER = "OTHER"


class ConcessionReason(StrEnum):
    NONE = "NONE"
    LISTING_PRICE_ADJUSTMENT = "LISTING_PRICE_ADJUSTMENT"
    REQUIREMENT_BUDGET_ADJUSTMENT = "REQUIREMENT_BUDGET_ADJUSTMENT"
    LISTING_TIMING_ADJUSTMENT = "LISTING_TIMING_ADJUSTMENT"
    REQUIREMENT_TIMING_ADJUSTMENT = "REQUIREMENT_TIMING_ADJUSTMENT"
    CONDITION_ADJUSTMENT = "CONDITION_ADJUSTMENT"
    ADDITIONAL_CONFIRMATION = "ADDITIONAL_CONFIRMATION"


class RejectionReason(StrEnum):
    PRICE_IMPOSSIBLE = "PRICE_IMPOSSIBLE"
    TIMING_IMPOSSIBLE = "TIMING_IMPOSSIBLE"
    CONDITION_IMPOSSIBLE = "CONDITION_IMPOSSIBLE"
    DECISION_AUTHORITY_BLOCKED = "DECISION_AUTHORITY_BLOCKED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    OTHER = "OTHER"


_COMPARISON_LABELS = {
    ComparisonReason.PRICE_FIT: "가격 조건이 상대적으로 잘 맞는다",
    ComparisonReason.TIMING_FIT: "시점 조건이 상대적으로 잘 맞는다",
    ComparisonReason.CONDITION_FIT: "협상 조건이 상대적으로 잘 맞는다",
    ComparisonReason.CONTACTABILITY_FIT: "접촉 가능성이 상대적으로 높다",
    ComparisonReason.OVERALL_FIT: "여러 핵심 조건의 종합 적합도가 상대적으로 높다",
}

_OBSTACLE_LABELS = {
    ObstacleReason.PRICE_GAP: "가격 차",
    ObstacleReason.TIMING_MISMATCH: "시점 차",
    ObstacleReason.CONDITION_CONFLICT: "조건 충돌",
    ObstacleReason.CONTACT_DIFFICULTY: "접촉 어려움",
    ObstacleReason.DECISION_AUTHORITY: "결정 권한 제약",
    ObstacleReason.INSUFFICIENT_EVIDENCE: "판단 근거 부족",
    ObstacleReason.OTHER: "기타 장애물",
}

_CONCESSION_LABELS = {
    ConcessionReason.LISTING_PRICE_ADJUSTMENT: "매물 측 가격 조정",
    ConcessionReason.REQUIREMENT_BUDGET_ADJUSTMENT: "손님 측 예산 조정",
    ConcessionReason.LISTING_TIMING_ADJUSTMENT: "매물 측 시점 조정",
    ConcessionReason.REQUIREMENT_TIMING_ADJUSTMENT: "손님 측 시점 조정",
    ConcessionReason.CONDITION_ADJUSTMENT: "협상 조건 조정",
    ConcessionReason.ADDITIONAL_CONFIRMATION: "추가 확인",
}

_REJECTION_LABELS = {
    RejectionReason.PRICE_IMPOSSIBLE: "가격 조건을 맞출 수 없다",
    RejectionReason.TIMING_IMPOSSIBLE: "시점 조건을 맞출 수 없다",
    RejectionReason.CONDITION_IMPOSSIBLE: "핵심 조건을 맞출 수 없다",
    RejectionReason.DECISION_AUTHORITY_BLOCKED: "결정 권한 제약으로 진행할 수 없다",
    RejectionReason.INSUFFICIENT_EVIDENCE: "판정에 필요한 근거가 부족하다",
    RejectionReason.OTHER: "기타 사유로 진행할 수 없다",
}


@dataclass(frozen=True)
class EvidenceCatalogEntry:
    """요청 카드가 이미 보유한 검증된 근거와 짧은 reference의 대응."""

    ref_id: int
    card_id: int
    evidence_side: NegotiationSide
    field_name: str
    source: Evidence


def _evidence_key(source: Evidence) -> str:
    return json.dumps(source.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)


def _card_evidence(card: JudgmentCard) -> tuple[tuple[str, Evidence], ...]:
    analysis = card.analysis
    collected: list[tuple[str, Evidence]] = [
        *(("intent", item) for item in analysis.intent.evidence),
        *(("urgency", item) for item in analysis.urgency.evidence),
    ]
    for assessment in analysis.price:
        collected.extend(
            (f"price.{assessment.price_kind.value}", item) for item in assessment.basis
        )
    for index, condition in enumerate(analysis.timing.constraints, start=1):
        collected.extend((f"timing.{index}", item) for item in condition.evidence)
    for field_name, conditions in (
        ("flexible", analysis.flexible),
        ("inflexible", analysis.inflexible),
    ):
        for index, condition in enumerate(conditions, start=1):
            collected.extend((f"{field_name}.{index}", item) for item in condition.evidence)
    collected.extend(("contactability", item) for item in analysis.contactability.evidence)
    return tuple(collected)


def build_evidence_catalog(request: BrokerageJudgmentRequest) -> tuple[EvidenceCatalogEntry, ...]:
    """앵커와 후보 카드의 중복 근거를 한 번씩만 싣는 안정적인 색인."""
    catalog: list[EvidenceCatalogEntry] = []
    seen: set[tuple[int, str]] = set()
    for card in (request.anchor, *request.candidates):
        for field_name, source in _card_evidence(card):
            key = (card.card_id, _evidence_key(source))
            if key in seen:
                continue
            seen.add(key)
            catalog.append(
                EvidenceCatalogEntry(
                    ref_id=len(catalog) + 1,
                    card_id=card.card_id,
                    evidence_side=card.negotiation_side,
                    field_name=field_name,
                    source=source,
                )
            )
    return tuple(catalog)


class ModelRecommendedAction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    contact_side: NegotiationSide
    channel: ContactChannel
    message: str = Field(min_length=1, max_length=JUDGMENT_ACTION_MAX_LENGTH)


class ModelCandidateJudgment(BaseModel):
    """후보 1건에 대한 모델의 압축된 판단만."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    card_id: int = Field(ge=1)
    grade: MatchGrade
    rank: int = Field(ge=1)
    comparison_reason: ComparisonReason
    comparison_detail: str | None = Field(default=None, max_length=JUDGMENT_DETAIL_MAX_LENGTH)
    obstacle_reason: ObstacleReason
    obstacle_detail: str | None = Field(default=None, max_length=JUDGMENT_DETAIL_MAX_LENGTH)
    concession_reason: ConcessionReason
    concession_detail: str | None = Field(default=None, max_length=JUDGMENT_DETAIL_MAX_LENGTH)
    recommended_action: ModelRecommendedAction | None = None
    rejection_reason: RejectionReason | None = None
    rejection_detail: str | None = Field(default=None, max_length=JUDGMENT_DETAIL_MAX_LENGTH)
    evidence_refs: tuple[int, ...] = Field(min_length=1, max_length=JUDGMENT_MAX_EVIDENCE_REFS)


class BrokerageJudgmentModelOutput(BaseModel):
    """모델이 채우는 중개 판정.

    계약 버전, 대상, 원문 근거, prompt/workflow version과 실행 제어 값은 이 schema에 없다.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidates: tuple[ModelCandidateJudgment, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def each_candidate_appears_once(self) -> Self:
        identifiers = [candidate.card_id for candidate in self.candidates]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("candidates must not repeat a card_id")
        return self


def _with_detail(label: str, detail: str | None) -> str:
    return f"{label}: {detail.strip()}" if detail and detail.strip() else label


def _optional_reason[ReasonT: StrEnum](
    reason: ReasonT, none_value: ReasonT, labels: dict[ReasonT, str], detail: str | None
) -> str | None:
    if reason is none_value:
        return None
    return _with_detail(labels[reason], detail)


def _assemble_evidence(
    request: BrokerageJudgmentRequest,
    candidate: ModelCandidateJudgment,
) -> tuple[JudgmentEvidence, ...]:
    catalog = {entry.ref_id: entry for entry in build_evidence_catalog(request)}
    allowed_card_ids = {request.anchor.card_id, candidate.card_id}
    assembled: list[JudgmentEvidence] = []
    seen: set[int] = set()
    for ref_id in candidate.evidence_refs:
        if ref_id in seen:
            continue
        seen.add(ref_id)
        entry = catalog.get(ref_id)
        if entry is None:
            raise BrokerageJudgmentContractError(f"unknown evidence reference {ref_id}")
        if entry.card_id not in allowed_card_ids:
            raise BrokerageJudgmentContractError(
                f"evidence reference {ref_id} belongs to another candidate"
            )
        assembled.append(
            JudgmentEvidence(
                evidence_side=entry.evidence_side,
                field_name=entry.field_name,
                source=entry.source,
            )
        )
    return tuple(assembled)


def assemble_candidates(
    request: BrokerageJudgmentRequest, output: BrokerageJudgmentModelOutput
) -> tuple[CandidateJudgment, ...]:
    """압축된 모델 판단을 기존 공개 결과로 결정적으로 복원한다."""
    judged = {candidate.card_id: candidate for candidate in output.candidates}
    ordered = [judged[card.card_id] for card in request.candidates if card.card_id in judged]
    # 요청에 없는 후보도 버리지 않는다. 검증이 문제를 드러내야 한다.
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
            comparison_basis=_with_detail(
                _COMPARISON_LABELS[candidate.comparison_reason], candidate.comparison_detail
            ),
            primary_obstacle=_optional_reason(
                candidate.obstacle_reason,
                ObstacleReason.NONE,
                _OBSTACLE_LABELS,
                candidate.obstacle_detail,
            ),
            possible_concession=_optional_reason(
                candidate.concession_reason,
                ConcessionReason.NONE,
                _CONCESSION_LABELS,
                candidate.concession_detail,
            ),
            recommended_action=(
                RecommendedAction(
                    contact_side=candidate.recommended_action.contact_side,
                    channel=candidate.recommended_action.channel,
                    message=candidate.recommended_action.message,
                )
                if candidate.recommended_action
                else None
            ),
            rejection_reason=(
                _with_detail(
                    _REJECTION_LABELS[candidate.rejection_reason], candidate.rejection_detail
                )
                if candidate.rejection_reason
                else None
            ),
            evidence=_assemble_evidence(request, candidate),
        )
        for candidate in ordered
    )
