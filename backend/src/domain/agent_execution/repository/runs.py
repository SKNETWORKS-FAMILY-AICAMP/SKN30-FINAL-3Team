from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Any, cast

from sqlalchemy import CursorResult, and_, case, func, not_, or_, text, update
from sqlmodel import Session, col, select

from domain.agent_execution.models import (
    ANCHOR_READY_STATUS,
    CROSS_JUDGMENT_RUN_TYPE,
    FAILED_TERMINAL_STATUS,
    IN_PROGRESS_STATUSES,
    LEDGER_SAVE_TRIGGER_TYPE,
    QUEUED_STATUS,
    RUNNING_STATUS,
    AgentRun,
    AnchorType,
)


def add_agent_run(session: Session, run: AgentRun) -> AgentRun:
    session.add(run)
    session.flush()
    return run


# 같은 앵커를 동시에 접수해도 실행이 하나만 생기게 하는 transaction advisory lock 이름공간.
# 다른 기능의 advisory lock과 키 공간이 겹치지 않게 고정 분류 번호를 앞에 둔다.
RUN_INTAKE_LOCK_NAMESPACE = 0x46330001


def lock_run_intake(
    session: Session, brokerage_id: int, anchor_type: AnchorType, anchor_id: int
) -> None:
    """같은 사무소·앵커의 실행 접수를 PostgreSQL transaction 범위에서 직렬화한다."""
    canonical = f"{brokerage_id}:{anchor_type.value}:{anchor_id}".encode()
    digest = hashlib.sha256(canonical).digest()
    # 2-인자 advisory lock의 두 키는 signed int32다. 해시 충돌은 관계없는 접수를 잠깐
    # 직렬화할 뿐 실행 재사용의 정확성을 깨뜨리지 않는다.
    anchor_key = int.from_bytes(digest[:4], "big", signed=True)
    session.execute(
        text("SELECT pg_advisory_xact_lock(:namespace, :anchor_key)"),
        {"namespace": RUN_INTAKE_LOCK_NAMESPACE, "anchor_key": anchor_key},
    )


REUSABLE_ACTIVE_STATUSES = (QUEUED_STATUS, *IN_PROGRESS_STATUSES)


def find_reusable_active_run(
    session: Session,
    brokerage_id: int,
    anchor_type: AnchorType,
    anchor_id: int,
    input_data_version: int,
) -> AgentRun | None:
    """같은 앵커·입력 버전으로 아직 진행 중인 최신 루트 실행을 찾는다."""
    listing_id = anchor_id if anchor_type is AnchorType.LISTING else None
    requirement_id = anchor_id if anchor_type is AnchorType.REQUIREMENT else None
    statement = (
        select(AgentRun)
        .where(
            *root_cross_judgment_conditions(),
            col(AgentRun.brokerage_id) == brokerage_id,
            col(AgentRun.target_listing_id).is_not_distinct_from(listing_id),
            col(AgentRun.target_requirement_id).is_not_distinct_from(requirement_id),
            col(AgentRun.input_data_version) == input_data_version,
            col(AgentRun.status).in_(list(REUSABLE_ACTIVE_STATUSES)),
        )
        .order_by(col(AgentRun.created_at).desc(), col(AgentRun.id).desc())
        .limit(1)
    )
    return session.execute(statement).scalars().first()


def park_ledger_save_run(
    session: Session, run_id: int, brokerage_id: int, worker_id: str, attempt_count: int
) -> int:
    """앵커 카드를 저장한 LEDGER_SAVE 실행을 주차하고 lease 를 비운다.

    `trigger_type` 을 조건에 넣어 주차와 사용자 승격을 같은 행에서 직렬화한다. Worker 가
    실행을 읽은 뒤 주차하기 전에 사용자 요청이 들어오면 조건이 어긋나 0행이 바뀌고,
    호출자는 주차 대신 후보 조회로 계속 간다. 조건을 두지 않으면 그 요청이 다음 lease
    만료까지 묻히고 계획된 handoff 가 실패 재시도로 처리된다.

    lease 를 비우는 이유는 사용자 승격이 곧바로 선점 대상이 되게 하기 위해서다. 주차
    조합은 선점과 최대 시도 정리 모두에서 제외되므로 lease 없이 남아도 집어가지 않는다.
    """
    statement = (
        update(AgentRun)
        .where(
            *root_cross_judgment_conditions(),
            col(AgentRun.id) == run_id,
            col(AgentRun.brokerage_id) == brokerage_id,
            col(AgentRun.trigger_type) == LEDGER_SAVE_TRIGGER_TYPE,
            col(AgentRun.status) == ANCHOR_READY_STATUS,
            col(AgentRun.lease_owner) == worker_id,
            col(AgentRun.attempt_count) == attempt_count,
        )
        .values(lease_owner=None, lease_expires_at=None, updated_at=func.now())
        .execution_options(synchronize_session=False)
    )
    return cast(CursorResult[Any], session.execute(statement)).rowcount


def resume_ledger_save_run(
    session: Session, run_id: int, brokerage_id: int, trigger_type: str
) -> int:
    """저장이 만든 활성 실행에 들어온 사용자 판정 요청을 같은 실행에 기록한다.

    QUEUED는 다음 최초 선점이 전체 실행을 하고, RUNNING은 현재 lease의 Worker가 앵커 카드
    뒤로 계속 간다. 이미 ANCHOR_READY에 주차됐다면 lease를 비워 즉시 이어받게 한다. 이
    이어받기는 실패 재시도가 아니므로 다음 선점에서 attempt_count를 늘리지 않는다.
    """
    parked = col(AgentRun.status) == ANCHOR_READY_STATUS
    statement = (
        update(AgentRun)
        .where(
            *root_cross_judgment_conditions(),
            col(AgentRun.id) == run_id,
            col(AgentRun.brokerage_id) == brokerage_id,
            col(AgentRun.trigger_type) == LEDGER_SAVE_TRIGGER_TYPE,
            col(AgentRun.status).in_(list(REUSABLE_ACTIVE_STATUSES)),
        )
        .values(
            trigger_type=trigger_type,
            lease_owner=case((parked, None), else_=col(AgentRun.lease_owner)),
            lease_expires_at=case((parked, None), else_=col(AgentRun.lease_expires_at)),
            updated_at=func.now(),
        )
        .execution_options(synchronize_session=False)
    )
    return cast(CursorResult[Any], session.execute(statement)).rowcount


def find_root_cross_judgment_run(
    session: Session, brokerage_id: int, run_id: int
) -> AgentRun | None:
    """사용자가 접수한 루트 교차 판정만 돌려준다. 내부 하위 실행은 조회 대상이 아니다."""
    statement = select(AgentRun).where(
        col(AgentRun.brokerage_id) == brokerage_id,
        col(AgentRun.id) == run_id,
        col(AgentRun.run_type) == CROSS_JUDGMENT_RUN_TYPE,
        col(AgentRun.parent_run_id).is_(None),
    )
    return session.execute(statement).scalars().first()


def root_cross_judgment_conditions() -> list[Any]:
    """Worker가 다루는 실행 범위. 내부 하위 실행과 다른 실행 유형은 건드리지 않는다."""
    return [
        col(AgentRun.run_type) == CROSS_JUDGMENT_RUN_TYPE,
        col(AgentRun.parent_run_id).is_(None),
    ]


def lock_claimable_run(session: Session, max_attempts: int) -> AgentRun | None:
    """선점 가능한 실행 1건을 잠근다. 다른 Worker가 잠근 행은 기다리지 않고 건너뛴다.

    만료 판정은 애플리케이션 시계가 아니라 DB의 now()를 기준으로 한다. Worker 서버끼리
    시간이 어긋나도 같은 기준으로 만료를 보게 된다.
    """
    statement = (
        select(AgentRun)
        .where(
            *root_cross_judgment_conditions(),
            # 저장이 만든 실행은 앵커 카드까지만 만들고 멈춘다. 사용자가 판정을 요청하면
            # `service` 가 trigger_type 을 옮겨 다시 선점 대상이 된다(F3-CR-01~04).
            not_(
                and_(
                    col(AgentRun.trigger_type) == LEDGER_SAVE_TRIGGER_TYPE,
                    col(AgentRun.status) == ANCHOR_READY_STATUS,
                )
            ),
            or_(
                col(AgentRun.status) == QUEUED_STATUS,
                # 사용자 요청이 ANCHOR_READY 주차 실행을 이어받은 최초 선점. lease가 없는
                # 계획된 handoff이므로 실패 재시도 횟수를 소비하지 않는다.
                and_(
                    col(AgentRun.trigger_type) != LEDGER_SAVE_TRIGGER_TYPE,
                    col(AgentRun.status) == ANCHOR_READY_STATUS,
                    col(AgentRun.lease_owner).is_(None),
                    col(AgentRun.lease_expires_at).is_(None),
                ),
                and_(
                    col(AgentRun.status).in_(list(IN_PROGRESS_STATUSES)),
                    col(AgentRun.lease_expires_at) < func.now(),
                    col(AgentRun.attempt_count) < max_attempts,
                ),
            ),
        )
        .order_by(col(AgentRun.created_at).asc(), col(AgentRun.id).asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    return session.execute(statement).scalars().first()


def mark_run_claimed(
    session: Session, run: AgentRun, worker_id: str, lease_seconds: int
) -> AgentRun:
    """잠근 실행에 lease를 건다.

    최초 QUEUED만 RUNNING으로 옮기고 진행 상태는 보존한다. 사용자 요청이 주차 실행을
    이어받는 lease 없는 첫 선점은 계획된 handoff이므로 attempt_count를 늘리지 않는다.
    """
    resumed_handoff = and_(
        col(AgentRun.trigger_type) != LEDGER_SAVE_TRIGGER_TYPE,
        col(AgentRun.status) == ANCHOR_READY_STATUS,
        col(AgentRun.lease_owner).is_(None),
        col(AgentRun.lease_expires_at).is_(None),
    )
    session.execute(
        update(AgentRun)
        .where(col(AgentRun.id) == run.id)
        .values(
            status=case(
                (col(AgentRun.status) == QUEUED_STATUS, RUNNING_STATUS),
                else_=col(AgentRun.status),
            ),
            lease_owner=worker_id,
            lease_expires_at=func.now() + func.make_interval(0, 0, 0, 0, 0, 0, lease_seconds),
            attempt_count=case(
                (resumed_handoff, col(AgentRun.attempt_count)),
                else_=col(AgentRun.attempt_count) + 1,
            ),
            started_at=func.coalesce(col(AgentRun.started_at), func.now()),
            updated_at=func.now(),
        )
        .execution_options(synchronize_session=False)
    )
    session.refresh(run)
    return run


def fail_runs_over_attempt_limit(
    session: Session, max_attempts: int, failure_code: str, failure_message: str
) -> int:
    """상한을 넘겨 만료된 실행을 종료 처리하고 lease를 비운다.

    앵커 카드까지 성공한 LEDGER_SAVE 실행은 실패한 작업이 아니라 사용자 요청을 기다리는
    주차 실행이므로 제외한다. 바꾼 행 수를 돌려준다.
    """
    statement = (
        update(AgentRun)
        .where(
            *root_cross_judgment_conditions(),
            not_(
                and_(
                    col(AgentRun.trigger_type) == LEDGER_SAVE_TRIGGER_TYPE,
                    col(AgentRun.status) == ANCHOR_READY_STATUS,
                )
            ),
            col(AgentRun.status).in_(list(IN_PROGRESS_STATUSES)),
            col(AgentRun.lease_expires_at) < func.now(),
            col(AgentRun.attempt_count) >= max_attempts,
        )
        .values(
            status=FAILED_TERMINAL_STATUS,
            failure_code=failure_code,
            failure_message=failure_message,
            completed_at=func.now(),
            updated_at=func.now(),
            lease_owner=None,
            lease_expires_at=None,
        )
        .execution_options(synchronize_session=False)
    )
    result = cast(CursorResult[Any], session.execute(statement))
    return result.rowcount


def find_leased_run(
    session: Session,
    run_id: int,
    worker_id: str,
    attempt_count: int,
    status: str | Sequence[str] = RUNNING_STATUS,
) -> AgentRun | None:
    """이 Worker가 아직 유효한 lease를 쥔 실행만 돌려준다.

    만료 판정은 애플리케이션 시계가 아니라 DB의 now()를 쓴다. attempt_count 까지 맞춰야
    같은 Worker가 이전 시도의 결과를 뒤늦게 밀어넣는 것을 막는다.

    `status`는 이 단계가 기대하는 상태다. 재개 가능한 단계는 허용 상태 묶음을 넘길 수 있다.
    기대와 다른 상태의 실행을 집어 처리하면 이미 끝난 단계를 다시 쓰거나 건너뛰게 된다.
    """
    status_condition = (
        col(AgentRun.status) == status
        if isinstance(status, str)
        else col(AgentRun.status).in_(list(status))
    )
    statement = select(AgentRun).where(
        *root_cross_judgment_conditions(),
        col(AgentRun.id) == run_id,
        status_condition,
        col(AgentRun.lease_owner) == worker_id,
        col(AgentRun.attempt_count) == attempt_count,
        col(AgentRun.lease_expires_at) > func.now(),
    )
    return session.execute(statement).scalars().first()


def mark_run_anchor_ready(
    session: Session,
    run_id: int,
    brokerage_id: int,
    worker_id: str,
    attempt_count: int,
    *,
    output_snapshot: dict[str, Any],
    input_tokens: int,
    output_tokens: int,
    latency_ms: int | None,
) -> int:
    """lease 를 아직 쥐고 있을 때만 상태를 옮긴다. 바꾼 행 수를 돌려준다.

    `completed_at`은 채우지 않는다. `ANCHOR_READY`는 중간 상태이고 lease 세 값은 다음 단계가
    같은 fencing 을 이어받도록 그대로 둔다.
    """
    statement = (
        update(AgentRun)
        .where(
            *root_cross_judgment_conditions(),
            col(AgentRun.id) == run_id,
            col(AgentRun.brokerage_id) == brokerage_id,
            col(AgentRun.status) == RUNNING_STATUS,
            col(AgentRun.lease_owner) == worker_id,
            col(AgentRun.attempt_count) == attempt_count,
            col(AgentRun.lease_expires_at) > func.now(),
        )
        .values(
            status=ANCHOR_READY_STATUS,
            redacted_output_snapshot=output_snapshot,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            updated_at=func.now(),
        )
        .execution_options(synchronize_session=False)
    )
    return cast(CursorResult[Any], session.execute(statement)).rowcount


def advance_run_status(
    session: Session,
    run_id: int,
    brokerage_id: int,
    worker_id: str,
    attempt_count: int,
    *,
    expected_status: str,
    next_status: str,
    output_snapshot: dict[str, Any] | None = None,
    completed: bool = False,
    add_input_tokens: int = 0,
    add_output_tokens: int = 0,
    add_latency_ms: int = 0,
) -> int:
    """lease 를 아직 쥐고 있고 상태가 기대값일 때만 다음 단계로 옮긴다.

    lease 세 값은 그대로 둔다. 다음 단계가 같은 fencing 을 이어받아야 중간에 다른 Worker 가
    끼어들지 못한다. `completed_at` 은 종료 상태에서만 채운다.
    """
    values: dict[str, Any] = {"status": next_status, "updated_at": func.now()}
    if output_snapshot is not None:
        values["redacted_output_snapshot"] = output_snapshot
    if completed:
        values["completed_at"] = func.now()
    # 토큰과 지연은 단계마다 더한다. 실행 하나의 총량이라야 비용 추적이 성립한다.
    if add_input_tokens:
        values["input_tokens"] = col(AgentRun.input_tokens) + add_input_tokens
    if add_output_tokens:
        values["output_tokens"] = col(AgentRun.output_tokens) + add_output_tokens
    if add_latency_ms:
        values["latency_ms"] = func.coalesce(col(AgentRun.latency_ms), 0) + add_latency_ms
    statement = (
        update(AgentRun)
        .where(
            *root_cross_judgment_conditions(),
            col(AgentRun.id) == run_id,
            col(AgentRun.brokerage_id) == brokerage_id,
            col(AgentRun.status) == expected_status,
            col(AgentRun.lease_owner) == worker_id,
            col(AgentRun.attempt_count) == attempt_count,
            col(AgentRun.lease_expires_at) > func.now(),
        )
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    return cast(CursorResult[Any], session.execute(statement)).rowcount


def fail_run(
    session: Session,
    run_id: int,
    brokerage_id: int,
    worker_id: str,
    attempt_count: int,
    *,
    status: str,
    failure_code: str,
    failure_message: str,
) -> int:
    """현재 lease를 가진 실행을 종료하고 공개 가능한 고정 실패 정보만 저장한다."""
    statement = (
        update(AgentRun)
        .where(
            *root_cross_judgment_conditions(),
            col(AgentRun.id) == run_id,
            col(AgentRun.brokerage_id) == brokerage_id,
            col(AgentRun.status).in_(list(IN_PROGRESS_STATUSES)),
            col(AgentRun.lease_owner) == worker_id,
            col(AgentRun.attempt_count) == attempt_count,
            col(AgentRun.lease_expires_at) > func.now(),
        )
        .values(
            status=status,
            failure_code=failure_code,
            failure_message=failure_message,
            completed_at=func.now(),
            updated_at=func.now(),
            lease_owner=None,
            lease_expires_at=None,
        )
        .execution_options(synchronize_session=False)
    )
    return cast(CursorResult[Any], session.execute(statement)).rowcount


def release_lease(
    session: Session,
    run_id: int,
    brokerage_id: int,
    worker_id: str,
    attempt_count: int,
) -> int:
    """재시도 가능한 실패에서 상태를 보존하고 lease 만 DB 현재 시각으로 만료시킨다."""
    statement = (
        update(AgentRun)
        .where(
            *root_cross_judgment_conditions(),
            col(AgentRun.id) == run_id,
            col(AgentRun.brokerage_id) == brokerage_id,
            col(AgentRun.status).in_(list(IN_PROGRESS_STATUSES)),
            col(AgentRun.lease_owner) == worker_id,
            col(AgentRun.attempt_count) == attempt_count,
            col(AgentRun.lease_expires_at) > func.now(),
        )
        # claim 조건이 `< now()` 이므로 같은 timestamp를 쓰면 빠른 다음 transaction에서
        # 경계값이 같아 한 번 건너뛸 수 있다. 확실히 과거로 보내 즉시 재선점 가능하게 한다.
        .values(
            lease_expires_at=func.now() - func.make_interval(0, 0, 0, 0, 0, 0, 1),
            updated_at=func.now(),
        )
        .execution_options(synchronize_session=False)
    )
    return cast(CursorResult[Any], session.execute(statement)).rowcount


def renew_lease(
    session: Session,
    run_id: int,
    brokerage_id: int,
    worker_id: str,
    attempt_count: int,
    lease_seconds: int,
) -> int:
    """Never revive an expired, released, completed or replaced claim."""
    statement = (
        update(AgentRun)
        .where(
            *root_cross_judgment_conditions(),
            col(AgentRun.id) == run_id,
            col(AgentRun.brokerage_id) == brokerage_id,
            col(AgentRun.lease_owner) == worker_id,
            col(AgentRun.attempt_count) == attempt_count,
            col(AgentRun.lease_expires_at) > func.now(),
            col(AgentRun.status).in_(list(IN_PROGRESS_STATUSES)),
        )
        .values(lease_expires_at=func.now() + func.make_interval(0, 0, 0, 0, 0, 0, lease_seconds))
        .execution_options(synchronize_session=False)
    )
    return cast(CursorResult[Any], session.execute(statement)).rowcount
