from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from domain.agent_execution.models import AgentRun, AnchorType


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
        if run.target_listing_id is not None:
            anchor_type = AnchorType.LISTING
            anchor_id = run.target_listing_id
        else:
            anchor_type = AnchorType.REQUIREMENT
            anchor_id = run.target_requirement_id or 0
        return cls(
            run_id=run.id or 0,
            run_group_id=run.run_group_id,
            status=run.status,
            anchor_type=anchor_type,
            anchor_id=anchor_id,
            input_data_version=run.input_data_version,
            created_at=run.created_at,
        )
