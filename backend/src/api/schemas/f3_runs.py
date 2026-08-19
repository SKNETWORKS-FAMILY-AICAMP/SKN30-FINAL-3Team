from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from domain.agent_execution.models import AgentRun, AgentRunAnchorError, AnchorType


class F3RunCreateRequest(BaseModel):
    """실행 요청은 앵커만 받는다. 사무소·요청자·상태는 서버가 정한다."""

    model_config = ConfigDict(extra="forbid")

    anchor_type: AnchorType
    anchor_id: int = Field(ge=1)


def anchor_of(run: AgentRun) -> tuple[AnchorType, int]:
    """실행 대상 컬럼에서 공개용 앵커를 되돌린다. 두 응답이 같은 규칙을 쓰게 한다.

    DB에는 둘 중 하나만 채우라는 CHECK 제약이 없다. 어느 쪽도 없거나 양쪽이 다 있는 행을
    억지로 변환하면 존재하지 않는 앵커를 정상 응답으로 내보내므로 여기서 멈춘다.
    """
    listing_id = run.target_listing_id
    requirement_id = run.target_requirement_id
    if listing_id is not None and requirement_id is None:
        return AnchorType.LISTING, listing_id
    if requirement_id is not None and listing_id is None:
        return AnchorType.REQUIREMENT, requirement_id
    raise AgentRunAnchorError(
        "agent run must target exactly one of a listing or a requirement"
    )


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
        """사무소·요청자·모델 설정과 입출력 스냅샷은 공개하지 않는다."""
        anchor_type, anchor_id = anchor_of(run)
        return cls(
            run_id=run.id or 0,
            status=run.status,
            anchor_type=anchor_type,
            anchor_id=anchor_id,
            input_data_version=run.input_data_version,
            created_at=run.created_at,
            started_at=run.started_at,
            completed_at=run.completed_at,
            failure_code=run.failure_code,
            failure_message=run.failure_message,
        )
