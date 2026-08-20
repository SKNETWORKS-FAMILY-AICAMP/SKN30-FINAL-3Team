from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from domain.agent_execution.models import (
    LEASE_EXPIRED_FAILURE_CODE,
    LEASE_EXPIRED_FAILURE_MESSAGE,
    AgentRun,
    AnchorType,
    anchor_of,
)

# DB의 failure_message는 외부 AI 오류 원문·내부 예외·개인정보가 들어올 수 있는 내부 운영
# 정보다. 공개 응답은 원문을 쓰지 않고 아래 allowlist에 있는 코드만 고정 문구로 변환한다.
PUBLIC_FAILURE_MESSAGES = {
    LEASE_EXPIRED_FAILURE_CODE: LEASE_EXPIRED_FAILURE_MESSAGE,
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
