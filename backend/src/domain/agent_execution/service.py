from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

import structlog
from brokerage_ai.f3 import InputPrivacyMode
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
    LEDGER_SAVE_TRIGGER_TYPE,
    QUEUED_STATUS,
    USER_REQUEST_TRIGGER_TYPE,
    AgentRun,
    AnchorType,
    InputVersionChangedError,
    LeaseNotHeldError,
    anchor_of,
)

logger = structlog.get_logger()

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
    *,
    trigger_type: str = USER_REQUEST_TRIGGER_TYPE,
) -> AgentRun:
    """F3 실행을 적재하거나 같은 앵커·입력 버전의 활성 실행을 반환한다.

    완료 결과는 여기서 재사용하지 않는다. 앵커 ``row_version``만으로는 상담 로그·세대·단지·
    당사자 관계와 AI 구성이 그대로인지 증명할 수 없기 때문이다. 완료 결과 재사용은 그 입력
    identity를 접수 시점에 검증할 수 있을 때 별도로 연다.
    """

    try:
        # 프로세스 메모리 lock은 API 인스턴스 사이의 동시 접수를 막지 못한다. 앵커 조회보다
        # 먼저 DB lock을 잡아 기다리는 동안 입력 버전이 바뀌어도 잠금 뒤의 최신 값을 읽는다.
        repository.lock_run_intake(session, brokerage_id, anchor_type, anchor_id)
        anchor = resolve_anchor(session, brokerage_id, anchor_type, anchor_id)
        existing = repository.find_reusable_active_run(
            session,
            brokerage_id,
            anchor_type,
            anchor_id,
            anchor.input_data_version,
        )
        if existing is not None:
            # 저장이 만든 실행이 어느 단계에 있든 사용자 판정 요청을 기억한다. QUEUED면 첫
            # Worker가 전체 실행을 하고, RUNNING이면 현재 Worker가 계속 가며, ANCHOR_READY면
            # lease를 비운 뒤 같은 실행을 후보 조회부터 이어받는다.
            if (
                trigger_type != LEDGER_SAVE_TRIGGER_TYPE
                and existing.trigger_type == LEDGER_SAVE_TRIGGER_TYPE
            ):
                previous_status = existing.status
                changed = repository.resume_ledger_save_run(
                    session, existing.id or 0, brokerage_id, trigger_type
                )
                session.commit()
                session.refresh(existing)
                if changed == 1:
                    logger.info(
                        "f3_ledger_save_run_resumed",
                        run_id=existing.id,
                        anchor_type=anchor_type.value,
                        anchor_id=anchor_id,
                        previous_status=previous_status,
                    )
                return existing
            session.commit()
            return existing

        run = AgentRun(
            brokerage_id=brokerage_id,
            run_group_id=uuid4(),
            parent_run_id=None,
            run_type=CROSS_JUDGMENT_RUN_TYPE,
            agent_type=BROKERAGE_WORKFLOW_AGENT_TYPE,
            status=QUEUED_STATUS,
            trigger_type=trigger_type,
            requested_by=requested_by,
            model_config_id=None,
            target_listing_id=anchor.target_listing_id,
            target_unit_id=anchor.target_unit_id,
            target_requirement_id=anchor.target_requirement_id,
            input_data_version=anchor.input_data_version,
            redacted_input_snapshot=redacted_input_snapshot(anchor),
            redacted_output_snapshot={},
        )
        repository.add_agent_run(session, run)
        session.commit()
    except BaseException:
        # 도메인 오류와 DB 오류 모두 transaction을 닫는다. 실행 레코드가 반쯤 남으면 Worker가
        # 대상 없는 작업을 집어가고 advisory lock도 transaction 종료까지 유지된다.
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
        terminal_count = repository.fail_runs_over_attempt_limit(
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

    if terminal_count > 0:
        # The cleanup and claim share a transaction; log only after its commit succeeds.
        logger.error(
            "ai_terminal_failure",
            component="ai",
            source="f3",
            status="FAILED_TERMINAL",
            failure_stage="EXECUTION",
            attempt=MAX_CLAIM_ATTEMPTS,
            failure_category="LEASE",
            error_code=LEASE_EXPIRED_FAILURE_CODE,
            error_type="AttemptLimitExceeded",
            terminal_count=terminal_count,
        )

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


def current_target_version(
    session: Session, brokerage_id: int, anchor_type: AnchorType, anchor_id: int
) -> int:
    """장부 대상 한 건의 현재 `row_version`.

    앵커와 후보가 같은 함수를 쓴다. 조회 범위도 F1 과 같으므로 화면에서 사라진 대상은
    버전을 돌려주지 않고 `NotFoundError` 가 된다.
    """
    if anchor_type is AnchorType.LISTING:
        listing = repository.find_listing_anchor(session, brokerage_id, anchor_id)
        if listing is None:
            raise NotFoundError("property listing is not found")
        return listing.row_version
    requirement = repository.find_requirement_anchor(session, brokerage_id, anchor_id)
    if requirement is None:
        raise NotFoundError("property requirement is not found")
    return requirement.row_version


def current_anchor_version(
    session: Session, run: AgentRun, anchor_type: AnchorType, anchor_id: int
) -> int:
    return current_target_version(session, run.brokerage_id, anchor_type, anchor_id)


def prepare_anchor_position_card(
    session: Session,
    run_id: int,
    worker_id: str,
    attempt_count: int,
    *,
    input_privacy_mode: InputPrivacyMode,
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
        input_privacy_mode=input_privacy_mode,
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
