"""F3 포지션 카드·매칭 판정의 공개 요청·응답 모델.

카드 원본은 `analysis_snapshot` 을 그대로 싣지 않고 화면이 쓰는 항목만 편다. 등급 근거는
축별 점수와 함께 내려 「왜 이 등급인가」를 서버 재계산 없이 설명할 수 있게 한다.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field, model_validator

from domain.negotiation.candidates import CandidateSelection
from domain.negotiation.service import CandidateOutcome, CardOutcome, MatchOutcome


class PositionCardCreateRequest(BaseModel):
    """세대 또는 구입장 중 하나만 지정한다."""

    unit_id: int | None = None
    requirement_id: int | None = None

    @model_validator(mode="after")
    def exactly_one_target(self) -> PositionCardCreateRequest:
        if (self.unit_id is None) == (self.requirement_id is None):
            raise ValueError("exactly one of unit_id or requirement_id is required")
        return self


class EvidenceItem(BaseModel):
    """근거 원문이 없으면 `is_inferred` 가 참이다 (수용 기준 2)."""

    field_name: str
    value: str | None
    quote: str | None
    is_inferred: bool


class PositionCardResponse(BaseModel):
    analysis_id: int
    label: str
    cache_hit: bool
    intent: str
    estimated_price: float | None
    price_conflict: str | None
    concession: float | None
    urgency: str
    flexible: list[str]
    inflexible: list[str]
    contactability: str
    contact_route: str | None
    deal_type_now: str
    speakers: list[str]
    evidence: list[EvidenceItem]

    @classmethod
    def from_domain(cls, outcome: CardOutcome) -> PositionCardResponse:
        card = outcome.card
        return cls(
            analysis_id=outcome.analysis_id,
            label=outcome.label,
            cache_hit=outcome.cache_hit,
            intent=card.intent.value,
            estimated_price=card.price.estimated,
            price_conflict=card.price.conflict,
            concession=card.price.concession,
            urgency=card.urgency.value,
            flexible=list(card.flexible),
            inflexible=list(card.inflexible),
            contactability=card.contactability.status,
            contact_route=card.contactability.route,
            deal_type_now=card.deal_type_now.value,
            speakers=[speaker.key for speaker in card.speakers],
            evidence=[
                EvidenceItem(
                    field_name=name,
                    value=value,
                    quote=quote,
                    is_inferred=quote is None,
                )
                for name, value, quote in (
                    ("intent", card.intent.value, card.intent.evidence),
                    (
                        "price",
                        None if card.price.estimated is None else str(card.price.estimated),
                        card.price.basis,
                    ),
                    ("urgency", card.urgency.value, card.urgency.evidence),
                    ("deal_type_now", card.deal_type_now.value, card.deal_type_now.ref),
                )
            ],
        )


class AxisScoreResponse(BaseModel):
    points: float
    note: str


class MatchCandidateResponse(BaseModel):
    unit_id: int
    label: str
    grade: str
    score: float | None
    rank: int
    hard_gates: list[str]
    hold: list[str]
    flags: list[str]
    axes: dict[str, AxisScoreResponse]
    blocker: str | None
    concession: str | None
    action: str | None

    @classmethod
    def from_domain(cls, rank: int, outcome: CandidateOutcome) -> MatchCandidateResponse:
        result = outcome.result
        return cls(
            unit_id=outcome.unit_id,
            label=outcome.label,
            grade=result.grade,
            score=result.score,
            rank=rank,
            hard_gates=list(result.hard),
            hold=list(result.hold),
            flags=list(result.flags),
            axes={
                name: AxisScoreResponse(points=round(axis.points, 2), note=axis.note)
                for name, axis in result.axes.items()
            },
            blocker=outcome.blocker,
            concession=outcome.concession,
            action=outcome.action,
        )


class DroppedCandidateResponse(BaseModel):
    unit_id: int
    label: str
    book_amount: float
    reason: str


class CandidateSelectionResponse(BaseModel):
    """후보 추출 결과. LLM 을 타기 전에 무엇이 왜 빠졌는지 그대로 보인다."""

    cap: float
    gate: float
    considered: int
    kept: int
    dropped: list[DroppedCandidateResponse]

    @classmethod
    def from_domain(cls, selection: CandidateSelection) -> CandidateSelectionResponse:
        return cls(
            cap=selection.cap,
            gate=round(selection.gate, 4),
            considered=selection.total,
            kept=len(selection.kept),
            dropped=[
                DroppedCandidateResponse(
                    unit_id=item.unit_id,
                    label=item.label,
                    book_amount=item.book_amount,
                    reason=item.reason,
                )
                for item in selection.dropped
            ],
        )


class MatchEvaluationCreateRequest(BaseModel):
    requirement_id: int
    as_of: date | None = Field(
        default=None,
        description="인도 가능일 계산의 기준일. 생략하면 오늘. 케이스 재현용이다.",
    )
    case_key: str | None = Field(default=None, max_length=120)


class MatchEvaluationResponse(BaseModel):
    evaluation_id: int
    anchor_label: str
    selection: CandidateSelectionResponse
    candidates: list[MatchCandidateResponse]
    llm_calls: int
    cache_hits: int

    @classmethod
    def from_domain(cls, outcome: MatchOutcome) -> MatchEvaluationResponse:
        return cls(
            evaluation_id=outcome.evaluation_id,
            anchor_label=outcome.anchor_label,
            selection=CandidateSelectionResponse.from_domain(outcome.selection),
            candidates=[
                MatchCandidateResponse.from_domain(rank, item)
                for rank, item in enumerate(outcome.candidates, start=1)
            ],
            llm_calls=outcome.llm_calls,
            cache_hits=outcome.cache_hits,
        )
