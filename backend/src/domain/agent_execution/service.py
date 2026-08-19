from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from core.errors import NotFoundError
from domain.agent_execution import repository
from domain.agent_execution.models import (
    BROKERAGE_WORKFLOW_AGENT_TYPE,
    CROSS_JUDGMENT_RUN_TYPE,
    QUEUED_STATUS,
    USER_REQUEST_TRIGGER_TYPE,
    AgentRun,
    AnchorType,
)

# Worker 선점 정책. heartbeat 없이 lease 만료만으로 장애 Worker의 작업을 회수한다.
LEASE_DURATION_SECONDS = 300
MAX_CLAIM_ATTEMPTS = 3
LEASE_EXPIRED_FAILURE_CODE = "LEASE_EXPIRED_MAX_ATTEMPTS"
# 개인정보와 내부 예외를 담지 않는 고정 문구를 쓴다.
LEASE_EXPIRED_FAILURE_MESSAGE = "실행이 최대 시도 횟수를 초과해 종료되었습니다"


@dataclass(frozen=True)
class ResolvedAnchor:
    """검증을 마친 실행 대상. 중복 실행 판정에 필요한 값을 한곳에 모은다 (F3-CM-05)."""

    anchor_type: AnchorType
    anchor_id: int
    input_data_version: int
    target_listing_id: int | None
    target_unit_id: int | None
    target_requirement_id: int | None


def resolve_anchor(
    session: Session, brokerage_id: int, anchor_type: AnchorType, anchor_id: int
) -> ResolvedAnchor:
    """앵커가 요청자의 사무소에 실재하는지 확인한다. 남의 사무소 식별자도 404로 답한다."""
    if anchor_type is AnchorType.LISTING:
        listing = repository.find_listing_anchor(session, brokerage_id, anchor_id)
        if listing is None:
            raise NotFoundError("property listing is not found")
        return ResolvedAnchor(
            anchor_type=anchor_type,
            anchor_id=anchor_id,
            input_data_version=listing.row_version,
            target_listing_id=listing.id,
            target_unit_id=listing.unit_id,
            target_requirement_id=None,
        )

    requirement = repository.find_requirement_anchor(session, brokerage_id, anchor_id)
    if requirement is None:
        raise NotFoundError("property requirement is not found")
    return ResolvedAnchor(
        anchor_type=anchor_type,
        anchor_id=anchor_id,
        input_data_version=requirement.row_version,
        target_listing_id=None,
        target_unit_id=None,
        target_requirement_id=requirement.id,
    )


def require_cross_judgment_run(session: Session, brokerage_id: int, run_id: int) -> AgentRun:
    """상태 조회용 실행 복구. 남의 사무소와 내부 하위 실행은 존재를 드러내지 않고 404로 답한다."""
    found = repository.find_root_cross_judgment_run(session, brokerage_id, run_id)
    if found is None:
        raise NotFoundError("agent run is not found")
    return found


def redacted_input_snapshot(anchor: ResolvedAnchor) -> dict[str, object]:
    """실행 재현에 필요한 식별자와 버전만 남긴다. 상담 원문과 연락처는 넣지 않는다."""
    return {
        "anchor_type": anchor.anchor_type.value,
        "anchor_id": anchor.anchor_id,
        "input_data_version": anchor.input_data_version,
    }


def queue_cross_judgment_run(
    session: Session,
    brokerage_id: int,
    requested_by: int,
    anchor_type: AnchorType,
    anchor_id: int,
) -> AgentRun:
    """F3 교차 판정 실행을 QUEUED로 적재한다. 모델 호출은 Worker 단계에서 일어난다."""
    anchor = resolve_anchor(session, brokerage_id, anchor_type, anchor_id)

    # 같은 앵커·입력 버전의 활성 실행 재사용(F3-CR-12)은 아직 구현하지 않는다.
    # 재사용을 넣을 자리는 resolve_anchor 다음이며 적재 경로는 그대로 둘 수 있다.
    run = AgentRun(
        brokerage_id=brokerage_id,
        run_group_id=uuid4(),
        parent_run_id=None,
        run_type=CROSS_JUDGMENT_RUN_TYPE,
        agent_type=BROKERAGE_WORKFLOW_AGENT_TYPE,
        status=QUEUED_STATUS,
        trigger_type=USER_REQUEST_TRIGGER_TYPE,
        requested_by=requested_by,
        model_config_id=None,
        target_listing_id=anchor.target_listing_id,
        target_unit_id=anchor.target_unit_id,
        target_requirement_id=anchor.target_requirement_id,
        input_data_version=anchor.input_data_version,
        redacted_input_snapshot=redacted_input_snapshot(anchor),
        redacted_output_snapshot={},
    )

    try:
        repository.add_agent_run(session, run)
        session.commit()
    except SQLAlchemyError:
        # 실행 레코드가 반쯤 남으면 Worker가 대상 없는 작업을 집어간다.
        session.rollback()
        raise

    session.refresh(run)
    return run


def claim_next_run(session: Session, worker_id: str) -> AgentRun | None:
    """Worker가 처리할 실행 1건을 선점한다. 대상이 없으면 예외 없이 None을 돌려준다.

    상한 초과 정리와 선점을 한 트랜잭션에 둔다. 두 대상은 attempt_count 기준으로 서로
    겹치지 않는 행 집합이라 경쟁하지 않고, 하나로 묶으면 도중에 실패했을 때 종료 처리와
    선점이 함께 취소되어 어중간한 상태가 남지 않는다.
    """
    try:
        repository.fail_runs_over_attempt_limit(
            session,
            MAX_CLAIM_ATTEMPTS,
            LEASE_EXPIRED_FAILURE_CODE,
            LEASE_EXPIRED_FAILURE_MESSAGE,
        )
        locked = repository.lock_claimable_run(session, MAX_CLAIM_ATTEMPTS)
        claimed = (
            None
            if locked is None
            else repository.mark_run_claimed(
                session, locked, worker_id, LEASE_DURATION_SECONDS
            )
        )
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise

    return claimed
