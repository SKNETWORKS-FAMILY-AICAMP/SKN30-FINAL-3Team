from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from core.errors import NotFoundError
from domain.agent_execution import repository, snapshot
from domain.agent_execution.cache_key import position_card_cache_key
from domain.agent_execution.fingerprint import input_fingerprint
from domain.agent_execution.models import (
    BROKERAGE_WORKFLOW_AGENT_TYPE,
    CROSS_JUDGMENT_RUN_TYPE,
    LEASE_EXPIRED_FAILURE_CODE,
    LEASE_EXPIRED_FAILURE_MESSAGE,
    QUEUED_STATUS,
    USER_REQUEST_TRIGGER_TYPE,
    AgentRun,
    AnchorType,
    InputVersionChangedError,
    LeaseNotHeldError,
    anchor_of,
)

# Worker 선점 정책. heartbeat 없이 lease 만료만으로 장애 Worker의 작업을 회수한다.
LEASE_DURATION_SECONDS = 300
MAX_CLAIM_ATTEMPTS = 3


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
            else repository.mark_run_claimed(session, locked, worker_id, LEASE_DURATION_SECONDS)
        )
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise

    return claimed


@dataclass(frozen=True)
class PositionCardRequest:
    """카드가 없을 때 AI 생성에 넘길 최소 입력. 상담 원문·성명·연락처는 담지 않는다.

    interaction_count·last_interaction_at·max_interaction_id 는 이후 카드 저장 단계에서
    입력이 그대로인지 다시 확인할 fencing 값이다. 재검증 자체는 아직 구현하지 않았다.
    """

    cache_key: str
    negotiation_side: str
    anchor_type: AnchorType
    anchor_id: int
    data_version: int
    interaction_count: int
    last_interaction_at: datetime | None
    max_interaction_id: int | None
    agent_type: str
    model_config_id: int | None
    prompt_version: str | None
    workflow_version: str | None


@dataclass(frozen=True)
class AnchorCardLookup:
    """앵커 포지션 카드 조회 결과. 재사용 카드가 있으면 hit, 없으면 생성 요청이 붙는다."""

    cache_hit: bool
    cache_key: str
    negotiation_side: str
    anchor_type: AnchorType
    anchor_id: int
    data_version: int
    position_analysis_id: int | None = None
    generation_request: PositionCardRequest | None = None


def anchor_interaction_scope(
    session: Session, brokerage_id: int, anchor_type: AnchorType, anchor_id: int
) -> repository.InteractionScope:
    """대리 측면이 읽어도 되는 상담 로그 범위. 정의는 repository 한 곳에만 둔다."""
    return repository.build_interaction_scope(session, brokerage_id, anchor_type, anchor_id)


def anchor_interaction_summary(
    session: Session, run: AgentRun, anchor_type: AnchorType, anchor_id: int
) -> repository.InteractionSummary:
    """앵커 범위 상담 로그 집합의 신원."""
    scope = anchor_interaction_scope(session, run.brokerage_id, anchor_type, anchor_id)
    return repository.summarize_scoped_interactions(session, scope)


def current_anchor_version(
    session: Session, run: AgentRun, anchor_type: AnchorType, anchor_id: int
) -> int:
    if anchor_type is AnchorType.LISTING:
        listing = repository.find_listing_anchor(session, run.brokerage_id, anchor_id)
        if listing is None:
            raise NotFoundError("property listing is not found")
        return listing.row_version
    requirement = repository.find_requirement_anchor(session, run.brokerage_id, anchor_id)
    if requirement is None:
        raise NotFoundError("property requirement is not found")
    return requirement.row_version


def prepare_anchor_position_card(
    session: Session, run_id: int, worker_id: str, attempt_count: int
) -> AnchorCardLookup:
    """선점한 실행의 앵커 카드를 찾거나 생성 요청을 만든다. 아무것도 저장하지 않는다.

    유효한 카드를 확보하기 전이므로 ANCHOR_READY 전환은 이 단계에서 하지 않는다.
    """
    run = repository.find_leased_run(session, run_id, worker_id, attempt_count)
    if run is None:
        raise LeaseNotHeldError("the worker does not hold a valid lease on this run")

    anchor_type, anchor_id = anchor_of(run)
    if current_anchor_version(session, run, anchor_type, anchor_id) != run.input_data_version:
        raise InputVersionChangedError("the anchor changed after the run was queued")

    # cache key 입력은 실제 생성 경로와 **같은 조립 결과**에서 뽑는다. 여기서 따로 세면 두
    # 경로가 서로 다른 키를 만들어 한쪽의 cache hit 이 다른 쪽에서 miss 가 된다.
    assembled = snapshot.build_anchor_snapshot(
        session,
        run.brokerage_id,
        anchor_type,
        anchor_id,
        as_of=datetime.now(UTC),
        requested_by=run.requested_by,
    )
    source = assembled.request.source
    interactions = repository.InteractionSummary(
        source.interaction_count, source.last_interaction_at, source.max_interaction_id
    )
    # 앵커 카드는 앵커 자신을 대리하므로 측면이 앵커 종류를 따른다.
    # negotiation_side 어휘는 LISTING·REQUIREMENT 로 확정됐고 AnchorType 과 값이 같다.
    # 정본은 project-wiki 의 contracts/f3-ai.md 이고 AI 쪽 정의는 NegotiationSide 다.
    negotiation_side = anchor_type.value
    cache_key = position_card_cache_key(
        brokerage_id=run.brokerage_id,
        negotiation_side=negotiation_side,
        anchor_type=anchor_type.value,
        anchor_id=anchor_id,
        data_version=run.input_data_version,
        interaction_count=interactions.interaction_count,
        last_interaction_at=interactions.last_interaction_at,
        max_interaction_id=interactions.max_interaction_id,
        agent_type=run.agent_type,
        model_config_id=run.model_config_id,
        prompt_version=run.prompt_version,
        workflow_version=run.workflow_version,
        input_fingerprint=input_fingerprint(assembled.request),
        scope_identity=assembled.scope.identity(),
    )

    cached = repository.find_active_position_card(
        session,
        run.brokerage_id,
        cache_key=cache_key,
        negotiation_side=negotiation_side,
        listing_id=anchor_id if anchor_type is AnchorType.LISTING else None,
        requirement_id=anchor_id if anchor_type is AnchorType.REQUIREMENT else None,
        data_version=run.input_data_version,
        interactions=interactions,
    )
    common = {
        "cache_key": cache_key,
        "negotiation_side": negotiation_side,
        "anchor_type": anchor_type,
        "anchor_id": anchor_id,
        "data_version": run.input_data_version,
    }
    if cached is not None:
        return AnchorCardLookup(cache_hit=True, position_analysis_id=cached.id, **common)

    return AnchorCardLookup(
        cache_hit=False,
        generation_request=PositionCardRequest(
            interaction_count=interactions.interaction_count,
            last_interaction_at=interactions.last_interaction_at,
            max_interaction_id=interactions.max_interaction_id,
            agent_type=run.agent_type,
            model_config_id=run.model_config_id,
            prompt_version=run.prompt_version,
            workflow_version=run.workflow_version,
            **common,
        ),
        **common,
    )
