"""저장 판정 목록·대상·상세의 명시적 공개 HTTP 계약."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from api.schemas.f3_runs import F3AnchorCardResponse, F3CandidateResponse
from domain.agent_execution.models import AnchorType


class F3TargetLabelResponse(BaseModel):
    anchor_type: AnchorType
    anchor_id: int
    display_name: str
    property_unit_id: int | None
    assignee_id: int | None
    assignee_name: str | None
    trade_type: str | None
    complex_name: str | None
    current_conditions: str | None


class F3RecentRecordResponse(BaseModel):
    record_id: int
    record_type: Literal["INTERACTION", "FEEDBACK"]
    created_at: datetime | None
    scope: Literal["PAIR", "GENERAL"]
    anchor_type: AnchorType
    anchor_id: int
    interaction_id: int | None
    reason: str | None


class F3JudgmentCandidateResponse(F3CandidateResponse):
    current_eligibility: Literal["ELIGIBLE", "INELIGIBLE", "INSUFFICIENT_INPUT"]
    target: F3TargetLabelResponse
    position_card: F3AnchorCardResponse | None
    recent_records: list[F3RecentRecordResponse]


class F3JudgmentSummaryResponse(BaseModel):
    total_count: int
    judged_count: int
    strong_count: int
    weak_count: int
    rejected_count: int
    unjudged_count: int


class F3JudgmentTargetResponse(BaseModel):
    anchor: F3TargetLabelResponse
    is_synthetic_fixture: bool = False
    result_id: int | None
    run_id: int | None
    eligibility: Literal["ELIGIBLE", "INELIGIBLE", "INSUFFICIENT_INPUT"]
    eligibility_reason: str | None
    content_availability: Literal["AVAILABLE", "UNAVAILABLE"]
    freshness: Literal["CURRENT", "STALE", "NONE"]
    generation: Literal["IDLE", "QUEUED", "RUNNING", "FAILED"]
    generated_at: datetime | None
    meaningful_changed_at: datetime | None
    summary: F3JudgmentSummaryResponse | None
    representative_candidates: list[F3JudgmentCandidateResponse]


class F3AssigneeResponse(BaseModel):
    id: int
    display_name: str


class F3JudgmentListResponse(BaseModel):
    assignees: list[F3AssigneeResponse]
    items: list[F3JudgmentTargetResponse]
    counts: dict[str, int]
    next_cursor: str | None
    checked_at: datetime
    revision: str


class F3JudgmentDetailResponse(F3JudgmentTargetResponse):
    current_result_id: int | None
    candidates: list[F3JudgmentCandidateResponse]
    selected_candidate: F3JudgmentCandidateResponse | None
    next_cursor: str | None
    anchor_card: F3AnchorCardResponse | None
