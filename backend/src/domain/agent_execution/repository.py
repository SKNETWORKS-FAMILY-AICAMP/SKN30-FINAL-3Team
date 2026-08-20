from __future__ import annotations

from datetime import datetime
from typing import Any, NamedTuple, cast

from sqlalchemy import CursorResult, and_, func, or_, update
from sqlmodel import Session, col, select

from domain.agent_execution.models import (
    CROSS_JUDGMENT_RUN_TYPE,
    FAILED_TERMINAL_STATUS,
    QUEUED_STATUS,
    RUNNING_STATUS,
    AgentRun,
    NegotiationPositionAnalysis,
)
from domain.property_ledger import repository as ledger_repository
from domain.property_ledger.models import ClientInteraction, PropertyListing, PropertyRequirement


def add_agent_run(session: Session, run: AgentRun) -> AgentRun:
    session.add(run)
    session.flush()
    return run


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


def find_listing_anchor(
    session: Session, brokerage_id: int, listing_id: int
) -> PropertyListing | None:
    """매물 앵커. 조회 범위는 F1 매물장과 같아야 하므로 장부 repository를 그대로 쓴다."""
    return ledger_repository.find_property_listing(session, brokerage_id, listing_id)


def find_requirement_anchor(
    session: Session, brokerage_id: int, requirement_id: int
) -> PropertyRequirement | None:
    """손님 앵커. 장부 조회는 인물을 함께 돌려주지만 실행 대상은 구입장 행이다."""
    found = ledger_repository.find_property_requirement(session, brokerage_id, requirement_id)
    return found[0] if found is not None else None


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
            or_(
                col(AgentRun.status) == QUEUED_STATUS,
                and_(
                    col(AgentRun.status) == RUNNING_STATUS,
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
    """잠근 실행에 lease를 건다. started_at은 최초 선점에만 채우고 재선점에서는 보존한다."""
    session.execute(
        update(AgentRun)
        .where(col(AgentRun.id) == run.id)
        .values(
            status=RUNNING_STATUS,
            lease_owner=worker_id,
            lease_expires_at=func.now() + func.make_interval(0, 0, 0, 0, 0, 0, lease_seconds),
            attempt_count=col(AgentRun.attempt_count) + 1,
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
    """상한을 넘겨 만료된 실행을 종료 처리하고 lease를 비운다. 바꾼 행 수를 돌려준다."""
    statement = (
        update(AgentRun)
        .where(
            *root_cross_judgment_conditions(),
            col(AgentRun.status) == RUNNING_STATUS,
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
    session: Session, run_id: int, worker_id: str, attempt_count: int
) -> AgentRun | None:
    """이 Worker가 아직 유효한 lease를 쥔 실행만 돌려준다.

    만료 판정은 애플리케이션 시계가 아니라 DB의 now()를 쓴다. attempt_count 까지 맞춰야
    같은 Worker가 이전 시도의 결과를 뒤늦게 밀어넣는 것을 막는다.
    """
    statement = select(AgentRun).where(
        *root_cross_judgment_conditions(),
        col(AgentRun.id) == run_id,
        col(AgentRun.status) == RUNNING_STATUS,
        col(AgentRun.lease_owner) == worker_id,
        col(AgentRun.attempt_count) == attempt_count,
        col(AgentRun.lease_expires_at) > func.now(),
    )
    return session.execute(statement).scalars().first()


class InteractionSummary(NamedTuple):
    """상담 로그 집합의 신원. 시각 하나로는 과거 로그 추가와 무효화를 구분하지 못한다."""

    interaction_count: int
    last_interaction_at: datetime | None
    max_interaction_id: int | None


def summarize_interactions(
    session: Session,
    brokerage_id: int,
    *,
    unit_id: int | None = None,
    listing_id: int | None = None,
    requirement_id: int | None = None,
) -> InteractionSummary:
    """대상 상담 로그의 건수·마지막 시각·최대 ID 만 센다. 원문은 읽지 않는다."""
    targets = [
        column == value
        for column, value in (
            (col(ClientInteraction.unit_id), unit_id),
            (col(ClientInteraction.listing_id), listing_id),
            (col(ClientInteraction.requirement_id), requirement_id),
        )
        if value is not None
    ]
    if not targets:
        return InteractionSummary(0, None, None)

    statement = select(
        func.count(),
        func.max(col(ClientInteraction.interaction_at)),
        func.max(col(ClientInteraction.id)),
    ).where(
        col(ClientInteraction.brokerage_id) == brokerage_id,
        col(ClientInteraction.is_voided).is_(False),
        or_(*targets),
    )
    count, last_at, max_id = session.execute(statement).one()
    return InteractionSummary(int(count), last_at, max_id)


def find_active_position_card(
    session: Session,
    brokerage_id: int,
    *,
    cache_key: str,
    negotiation_side: str,
    listing_id: int | None,
    requirement_id: int | None,
    data_version: int,
    interactions: InteractionSummary,
) -> NegotiationPositionAnalysis | None:
    """재사용 가능한 카드만 돌려준다. 사무소·대상·측면·버전·상담 집합이 모두 맞아야 한다.

    cache_key 만 믿지 않고 저장된 source 값을 다시 대조한다. 키 계산식이 바뀌거나 예전
    schema 로 만든 행이 남아 있어도 낡은 카드를 재사용하지 않는다.
    """
    statement = select(NegotiationPositionAnalysis).where(
        col(NegotiationPositionAnalysis.brokerage_id) == brokerage_id,
        col(NegotiationPositionAnalysis.cache_key) == cache_key,
        col(NegotiationPositionAnalysis.negotiation_side) == negotiation_side,
        col(NegotiationPositionAnalysis.listing_id).is_not_distinct_from(listing_id),
        col(NegotiationPositionAnalysis.requirement_id).is_not_distinct_from(requirement_id),
        col(NegotiationPositionAnalysis.data_version) == data_version,
        col(NegotiationPositionAnalysis.source_interaction_count) == interactions.interaction_count,
        col(NegotiationPositionAnalysis.last_interaction_at).is_not_distinct_from(
            interactions.last_interaction_at
        ),
        col(NegotiationPositionAnalysis.invalidated_at).is_(None),
    )
    return session.execute(statement).scalars().first()
