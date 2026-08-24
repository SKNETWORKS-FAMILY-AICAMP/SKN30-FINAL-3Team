from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, NamedTuple, cast

from sqlalchemy import CursorResult, and_, case, func, literal, or_, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session, col, select

from core.errors import NotFoundError
from domain.agent_execution.models import (
    ANCHOR_READY_STATUS,
    CROSS_JUDGMENT_RUN_TYPE,
    FAILED_TERMINAL_STATUS,
    IN_PROGRESS_STATUSES,
    POSITION_CARD_CAPABILITY,
    QUEUED_STATUS,
    RUNNING_STATUS,
    AgentRun,
    AiModelConfig,
    AnchorType,
    MatchEvaluation,
    NegotiationPositionAnalysis,
    NegotiationPositionEvidence,
    NegotiationPositionPrice,
)
from domain.property_ledger import repository as ledger_repository
from domain.property_ledger.models import (
    ClientInteraction,
    Party,
    PropertyComplex,
    PropertyListing,
    PropertyRequirement,
    PropertyRequirementComplex,
    PropertyUnit,
    PropertyUnitPartyRelation,
)


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
    """매물 앵커. 조회 범위는 F1 매물장과 같아야 하므로 장부 repository를 그대로 쓴다.

    사무소, 매물 삭제 여부와 부모 세대 삭제 여부를 모두 그 조회가 판정한다. F3가 같은
    규칙을 따로 복사하면 F1이 범위를 바꿀 때 두 곳이 조용히 어긋난다.
    """
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
    """잠근 실행에 lease를 건다. 최초 QUEUED만 RUNNING으로 옮기고 진행 상태는 보존한다."""
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
    session: Session, run_id: int, worker_id: str, attempt_count: int, status: str = RUNNING_STATUS
) -> AgentRun | None:
    """이 Worker가 아직 유효한 lease를 쥔 실행만 돌려준다.

    만료 판정은 애플리케이션 시계가 아니라 DB의 now()를 쓴다. attempt_count 까지 맞춰야
    같은 Worker가 이전 시도의 결과를 뒤늦게 밀어넣는 것을 막는다.

    `status`는 이 단계가 기대하는 상태다. 단계마다 다르므로 인자로 받는다. 기대와 다른
    상태의 실행을 집어 처리하면 이미 끝난 단계를 다시 쓰거나 건너뛰게 된다.
    """
    statement = select(AgentRun).where(
        *root_cross_judgment_conditions(),
        col(AgentRun.id) == run_id,
        col(AgentRun.status) == status,
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


# 로그 포함 정책이 바뀌면 올린다. scope identity 에 들어가 캐시와 fencing 이 함께 갱신된다.
INTERACTION_SCOPE_CONTRACT_VERSION = "interaction-scope:v2"


@dataclass(frozen=True)
class InteractionScope:
    """대리 한쪽이 읽어도 되는 상담 로그의 범위.

    범위 정의를 여기 한 곳에만 둔다. 목록 조회와 신원 계산이 서로 다른 조건을 쓰면 AI에
    넘긴 로그와 cache key·fencing 이 어긋난다.

    `allowed_party_ids` 는 그 측면에 속한 당사자다. 같은 세대에 달린 로그라도 반대편
    당사자의 말은 읽지 않는다 (F3-LA-02, F3-CA-02). `counterparty_role` 문자열이 아니라
    F1 의 tenant 복합 관계와 `party_id` 를 기준으로 판정한다.
    """

    brokerage_id: int
    allowed_party_ids: frozenset[int]
    unit_id: int | None = None
    listing_id: int | None = None
    requirement_id: int | None = None

    def identity(self) -> str:
        """범위의 지문. 준비 시점과 저장 시점의 범위가 같은지 비교할 때 쓴다.

        digest 로 만든다. 당사자 ID 집합을 그대로 들고 다니면 오류 메시지나 로그로 새어
        나갈 자리가 생긴다.
        """
        canonical = json.dumps(
            {
                "schema": INTERACTION_SCOPE_CONTRACT_VERSION,
                "brokerage_id": self.brokerage_id,
                "unit_id": self.unit_id,
                "listing_id": self.listing_id,
                "requirement_id": self.requirement_id,
                "allowed_party_ids": sorted(self.allowed_party_ids),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return f"{INTERACTION_SCOPE_CONTRACT_VERSION}:{digest}"


def build_interaction_scope(
    session: Session, brokerage_id: int, anchor_type: AnchorType, anchor_id: int
) -> InteractionScope:
    """현재 F1 장부 관계에서 범위를 만든다.

    준비 단계와 저장 단계가 **같은 함수**를 쓴다. 저장 직전에 다시 부르면 그 사이에 생긴
    새 당사자 관계도 범위에 들어와 새 로그를 볼 수 있다.
    """
    if anchor_type is AnchorType.LISTING:
        listing = find_listing_anchor(session, brokerage_id, anchor_id)
        if listing is None:
            raise NotFoundError("property listing is not found")
        allowed = list_unit_related_party_ids(session, brokerage_id, listing.unit_id)
        if listing.client_party_id:
            allowed.add(listing.client_party_id)
        return InteractionScope(
            brokerage_id=brokerage_id,
            allowed_party_ids=frozenset(allowed),
            unit_id=listing.unit_id,
            listing_id=listing.id,
        )

    requirement = find_requirement_anchor(session, brokerage_id, anchor_id)
    if requirement is None:
        raise NotFoundError("property requirement is not found")
    allowed = {requirement.party_id}
    if requirement.co_broker_party_id:
        allowed.add(requirement.co_broker_party_id)
    return InteractionScope(
        brokerage_id=brokerage_id,
        allowed_party_ids=frozenset(allowed),
        requirement_id=requirement.id,
    )


def _scope_conditions(scope: InteractionScope) -> list[Any]:
    """범위 술어. 사무소, 무효화, 측면 대상, 허용 당사자를 모두 건다.

    매물 측은 대상 연결이 모호한 로그를 받지 않는다. 세대에만 달리고 당사자도 없는 로그는
    수요 측 상담일 수 있어 매물 대리 입력에서 제외한다. 반대편 정보가 한 건이라도 섞이는
    것보다 판단 재료가 한 건 줄어드는 쪽이 낫다 (F3-LA-02).
    """
    allowed = sorted(scope.allowed_party_ids)
    is_allowed_party = col(ClientInteraction.party_id).in_(allowed) if allowed else literal(False)

    if scope.requirement_id is not None:
        # 구입장 로그는 그 구입장에 달린 것만 본다. requirement_id 로 측면이 이미 확정되므로
        # 당사자가 비어 있어도 수요 측 기록이다.
        target = and_(
            col(ClientInteraction.requirement_id) == scope.requirement_id,
            or_(col(ClientInteraction.party_id).is_(None), is_allowed_party),
        )
    else:
        if scope.unit_id is None and scope.listing_id is None:
            return []
        # 매물 건에 명시적으로 달린 로그는 그 매물에 대한 기록이다.
        explicit_listing = (
            col(ClientInteraction.listing_id) == scope.listing_id
            if scope.listing_id is not None
            else literal(False)
        )
        # 세대에만 달린 로그는 허용 당사자가 말한 것일 때만 매물 측으로 본다.
        unit_only = (
            and_(
                col(ClientInteraction.listing_id).is_(None),
                col(ClientInteraction.unit_id) == scope.unit_id,
                is_allowed_party,
            )
            if scope.unit_id is not None
            else literal(False)
        )
        target = and_(
            # 구입장이 달린 로그는 그 자체로 수요 측이므로 항상 제외한다.
            col(ClientInteraction.requirement_id).is_(None),
            or_(explicit_listing, unit_only),
        )

    return [
        col(ClientInteraction.brokerage_id) == scope.brokerage_id,
        col(ClientInteraction.is_voided).is_(False),
        target,
    ]


def list_scoped_interactions(session: Session, scope: InteractionScope) -> list[ClientInteraction]:
    """범위 안의 유효 상담 로그 **전량**을 시간순으로 돌려준다.

    최신 N건으로 자르지 않는다. 과거 진술을 조용히 버리면 철회·정정 판정이 성립하지 않는다
    (F3-LA-05).
    """
    conditions = _scope_conditions(scope)
    if not conditions:
        return []
    statement = (
        select(ClientInteraction)
        .where(*conditions)
        .order_by(col(ClientInteraction.interaction_at).asc(), col(ClientInteraction.id).asc())
    )
    return list(session.execute(statement).scalars().all())


def summarize_scoped_interactions(session: Session, scope: InteractionScope) -> InteractionSummary:
    """같은 범위의 건수·마지막 시각·최대 ID. 원문은 읽지 않는다."""
    conditions = _scope_conditions(scope)
    if not conditions:
        return InteractionSummary(0, None, None)
    statement = select(
        func.count(),
        func.max(col(ClientInteraction.interaction_at)),
        func.max(col(ClientInteraction.id)),
    ).where(*conditions)
    count, last_at, max_id = session.execute(statement).one()
    return InteractionSummary(int(count), last_at, max_id)


def _active_position_card_conditions(
    brokerage_id: int,
    *,
    cache_key: str,
    negotiation_side: str,
    listing_id: int | None,
    requirement_id: int | None,
    data_version: int,
    interactions: InteractionSummary,
) -> list[Any]:
    """일반 cache lookup과 저장 단계 잠금 조회가 공유하는 활성 카드 조건."""
    return [
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
    ]


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
    """재사용 가능한 카드만 돌려준다. 준비 단계라 행 잠금을 잡지 않는다.

    cache_key 만 믿지 않고 저장된 source 값을 다시 대조한다. 키 계산식이 바뀌거나 예전
    schema 로 만든 행이 남아 있어도 낡은 카드를 재사용하지 않는다.
    """
    statement = select(NegotiationPositionAnalysis).where(
        *_active_position_card_conditions(
            brokerage_id,
            cache_key=cache_key,
            negotiation_side=negotiation_side,
            listing_id=listing_id,
            requirement_id=requirement_id,
            data_version=data_version,
            interactions=interactions,
        )
    )
    return session.execute(statement).scalars().first()


def lock_active_position_card_for_store(
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
    """저장할 cache hit 카드를 잠그고 transaction 끝까지 활성 상태를 고정한다.

    단순 재조회 뒤에 다른 transaction이 `invalidated_at`을 갱신하면 무효 카드 ID로 실행을
    확정할 수 있다. 저장 단계에서만 행 잠금을 잡아 그 갱신과 `ANCHOR_READY` 전이를
    직렬화한다. 모델을 호출하는 준비 단계에는 이 함수를 쓰지 않는다.
    """
    statement = (
        select(NegotiationPositionAnalysis)
        .where(
            *_active_position_card_conditions(
                brokerage_id,
                cache_key=cache_key,
                negotiation_side=negotiation_side,
                listing_id=listing_id,
                requirement_id=requirement_id,
                data_version=data_version,
                interactions=interactions,
            )
        )
        .with_for_update()
    )
    return session.execute(statement).scalars().first()


class ListingSnapshotRow(NamedTuple):
    """매물 앵커 조립에 필요한 장부 행 묶음. 반대편 데이터는 담기지 않는다."""

    listing: PropertyListing
    unit: PropertyUnit
    complex_row: PropertyComplex


def find_listing_snapshot(
    session: Session, brokerage_id: int, listing_id: int
) -> ListingSnapshotRow | None:
    """매물·세대·단지를 한 번에 읽는다. 삭제 범위는 F1 단건 조회와 같다."""
    statement = (
        select(PropertyListing, PropertyUnit, PropertyComplex)
        .join(
            PropertyUnit,
            (col(PropertyUnit.brokerage_id) == PropertyListing.brokerage_id)
            & (col(PropertyUnit.id) == PropertyListing.unit_id),
        )
        .join(
            PropertyComplex,
            (col(PropertyComplex.brokerage_id) == PropertyUnit.brokerage_id)
            & (col(PropertyComplex.id) == PropertyUnit.complex_id),
        )
        .where(
            col(PropertyListing.brokerage_id) == brokerage_id,
            col(PropertyListing.id) == listing_id,
            col(PropertyListing.is_deleted).is_(False),
            col(PropertyUnit.is_deleted).is_(False),
        )
    )
    row = session.execute(statement).first()
    return ListingSnapshotRow(row[0], row[1], row[2]) if row else None


class UnitPartyRole(NamedTuple):
    """비식별 역할 정보. 결정권 판정에만 쓰며 인물 식별자는 담지 않는다."""

    role: str
    is_primary: bool
    is_co_owner: bool
    party_id: int


def list_current_unit_party_roles(
    session: Session, brokerage_id: int, unit_id: int
) -> list[UnitPartyRole]:
    """현재 유효한 세대-인물 관계의 역할만 돌려준다. 성명과 연락처는 읽지 않는다."""
    statement = (
        select(
            col(PropertyUnitPartyRelation.role),
            col(PropertyUnitPartyRelation.is_primary),
            col(PropertyUnitPartyRelation.is_co_owner),
            col(PropertyUnitPartyRelation.party_id),
        )
        .where(
            col(PropertyUnitPartyRelation.brokerage_id) == brokerage_id,
            col(PropertyUnitPartyRelation.unit_id) == unit_id,
            col(PropertyUnitPartyRelation.valid_to).is_(None),
        )
        .order_by(
            col(PropertyUnitPartyRelation.role).asc(),
            col(PropertyUnitPartyRelation.role_index).asc(),
        )
    )
    return [UnitPartyRole(*row) for row in session.execute(statement).all()]


def list_unit_related_party_ids(session: Session, brokerage_id: int, unit_id: int) -> set[int]:
    """이 세대와 관계를 맺은 적 있는 모든 인물.

    `valid_to` 가 찬 과거 소유자·임차인도 포함한다. 그 사람의 말은 그 시점의 **매물 측**
    진술이고, 2018년 기록까지 남기는 F1 정책이 여기서 자산이 된다 (F3-LA-05). 반대편
    매수 희망자는 세대 관계 자체가 없어 이 집합에 들어오지 않는다.
    """
    statement = select(col(PropertyUnitPartyRelation.party_id)).where(
        col(PropertyUnitPartyRelation.brokerage_id) == brokerage_id,
        col(PropertyUnitPartyRelation.unit_id) == unit_id,
    )
    return set(session.execute(statement).scalars().all())


def list_requirement_complex_names(
    session: Session, brokerage_id: int, requirement_id: int
) -> list[str]:
    """희망 단지 이름. 선호 순서를 유지한다."""
    statement = (
        select(col(PropertyComplex.name))
        .join(
            PropertyRequirementComplex,
            (col(PropertyRequirementComplex.brokerage_id) == PropertyComplex.brokerage_id)
            & (col(PropertyRequirementComplex.complex_id) == PropertyComplex.id),
        )
        .where(
            col(PropertyRequirementComplex.brokerage_id) == brokerage_id,
            col(PropertyRequirementComplex.requirement_id) == requirement_id,
            col(PropertyComplex.is_deleted).is_(False),
        )
        .order_by(
            col(PropertyRequirementComplex.preference_order).asc().nullslast(),
            col(PropertyComplex.name).asc(),
        )
    )
    return list(session.execute(statement).scalars().all())


def lock_card_that_won_the_cache_key(
    session: Session, brokerage_id: int, cache_key: str
) -> NegotiationPositionAnalysis | None:
    """저장 경합에서 이긴 활성 카드를 잠그고 돌려준다.

    `ON CONFLICT DO NOTHING` 으로 밀린 쪽이 **이미 같은 키를 넣은 상대 카드**를 찾는 용도다.
    일반 cache lookup 에는 쓰지 않는다. 그쪽은 `find_active_position_card` 가 대상·버전·
    상담 집합까지 함께 대조한다. 이 행도 현재 실행이 확정될 때까지 무효화되면 안 되므로
    transaction 끝까지 잠근다.
    """
    statement = (
        select(NegotiationPositionAnalysis)
        .where(
            col(NegotiationPositionAnalysis.brokerage_id) == brokerage_id,
            col(NegotiationPositionAnalysis.cache_key) == cache_key,
            col(NegotiationPositionAnalysis.invalidated_at).is_(None),
        )
        .with_for_update()
    )
    return session.execute(statement).scalars().first()


def insert_position_card(
    session: Session, card: NegotiationPositionAnalysis
) -> NegotiationPositionAnalysis | None:
    """카드를 넣는다. 다른 실행이 같은 키를 먼저 넣었으면 None 을 돌려준다.

    partial unique index(`uq_position_analysis_active_cache_key`)와 같은 조건으로
    `ON CONFLICT DO NOTHING` 한다. 경합을 예외로 터뜨리면 정상 상황이 실패가 된다.
    """
    values = card.model_dump(exclude_none=True, exclude={"id"})
    statement = (
        pg_insert(NegotiationPositionAnalysis)
        .values(**values)
        .on_conflict_do_nothing(
            index_elements=["brokerage_id", "cache_key"],
            index_where=text("invalidated_at IS NULL"),
        )
        .returning(col(NegotiationPositionAnalysis.id))
    )
    inserted = session.execute(statement).scalars().first()
    if inserted is None:
        return None
    card.id = inserted
    return card


def insert_position_prices(session: Session, prices: Sequence[NegotiationPositionPrice]) -> None:
    if prices:
        session.add_all(list(prices))
        session.flush()


def insert_position_evidence(
    session: Session, evidence: Sequence[NegotiationPositionEvidence]
) -> None:
    if evidence:
        session.add_all(list(evidence))
        session.flush()


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


# model snapshot 에 담아도 되는 값. endpoint 전체 URL, API key, token 은 목록에 없다.
MODEL_SNAPSHOT_FIELDS = ("provider", "model_name", "model_version", "config_key", "config_version")


def find_position_card_model_config(
    session: Session, brokerage_id: int, model_config_id: int
) -> AiModelConfig | None:
    """이 사무소의 포지션 카드용 활성 설정만 돌려준다.

    다른 사무소의 설정은 여기서 걸러진다. 호출자는 `None` 을 존재 여부를 드러내지 않는 하나의
    오류로 바꾼다.
    """
    statement = select(AiModelConfig).where(
        col(AiModelConfig.brokerage_id) == brokerage_id,
        col(AiModelConfig.id) == model_config_id,
        col(AiModelConfig.capability) == POSITION_CARD_CAPABILITY,
        col(AiModelConfig.is_active).is_(True),
    )
    return session.execute(statement).scalars().first()


def safe_model_snapshot(config: AiModelConfig) -> dict[str, object]:
    """DB 설정에서 allowlist 필드만 뽑는다. 호출자가 준 임의 dict 를 그대로 쓰지 않는다."""
    return {field: getattr(config, field) for field in MODEL_SNAPSHOT_FIELDS}


def bind_run_execution_configuration(
    session: Session,
    run_id: int,
    brokerage_id: int,
    worker_id: str,
    attempt_count: int,
    *,
    model_config_id: int,
    model_snapshot: dict[str, object],
    prompt_version: str,
    workflow_version: str,
    expected_status: str = RUNNING_STATUS,
) -> int:
    """실행에 모델·프롬프트·워크플로 바인딩을 처음 기록한다.

    lease fencing 아래에서 네 값을 한 번에 쓴다. 미바인딩은 세 버전 컬럼이 NULL 이고
    `model_snapshot` 이 빈 객체인 상태뿐이다. 일부만 채워진 행은 `WHERE` 가 걸러내 조용히
    덮이지 않는다. 바꾼 행 수를 돌려준다.
    """
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
            col(AgentRun.model_config_id).is_(None),
            col(AgentRun.prompt_version).is_(None),
            col(AgentRun.workflow_version).is_(None),
            # model_snapshot 은 NOT NULL DEFAULT '{}' 이라 "NULL 이면 미바인딩"이 성립하지
            # 않는다. 빈 객체인지 JSONB 로 직접 비교한다.
            text("agent_run.model_snapshot::jsonb = '{}'::jsonb"),
        )
        .values(
            model_config_id=model_config_id,
            model_snapshot=model_snapshot,
            prompt_version=prompt_version,
            workflow_version=workflow_version,
            updated_at=func.now(),
        )
        .execution_options(synchronize_session=False)
    )
    return cast(CursorResult[Any], session.execute(statement)).rowcount


class CandidatePriceRow(NamedTuple):
    """카드에 실린 거래 유형별 금액. `display_order` 순서를 그대로 유지한다.

    월세는 보증금과 월 차임이 **별도 축**이라 네 값을 모두 들고 온다. 하나로 접으면 어느
    금액을 비교했는지 알 수 없게 된다.
    """

    price_kind: str
    stated_amount: int | None
    estimated_amount: int | None
    stated_monthly_amount: int | None
    estimated_monthly_amount: int | None


def list_position_card_prices(
    session: Session, brokerage_id: int, position_analysis_id: int
) -> list[CandidatePriceRow]:
    """카드의 금액을 원래 순서로 읽는다. 첫 행이 후보 조회의 가격 축이 된다."""
    statement = (
        select(NegotiationPositionPrice)
        .where(
            col(NegotiationPositionPrice.brokerage_id) == brokerage_id,
            col(NegotiationPositionPrice.position_analysis_id) == position_analysis_id,
        )
        .order_by(
            col(NegotiationPositionPrice.display_order).asc(),
            col(NegotiationPositionPrice.price_kind).asc(),
        )
    )
    return [
        CandidatePriceRow(
            price_kind=row.price_kind,
            stated_amount=row.stated_amount,
            estimated_amount=row.estimated_amount,
            stated_monthly_amount=row.stated_monthly_amount,
            estimated_monthly_amount=row.estimated_monthly_amount,
        )
        for row in session.execute(statement).scalars().all()
    ]


class UnitSpecification(NamedTuple):
    """후보 조회에 쓰는 세대 사양. 인물과 금액은 담지 않는다."""

    complex_id: int
    pyeong: Decimal | None


class RequirementSpecification(NamedTuple):
    """구입장 앵커가 어떤 거래를 원하는지. 후보 매물의 거래 유형을 여기서 정한다."""

    demand_type: str
    desired_pyeongs: tuple[Decimal, ...]


def find_requirement_specification(
    session: Session, brokerage_id: int, requirement_id: int
) -> RequirementSpecification | None:
    """구입장의 거래 구분과 희망 평형.

    `demand_type` 은 매물장과 어휘가 다르다. 매물장이 `매매`라고 부르는 것을 구입장은
    `매수`라고 부른다 (F1 데이터 항목 13.1·13.2).
    """
    statement = select(
        col(PropertyRequirement.demand_type), col(PropertyRequirement.desired_pyeongs)
    ).where(
        col(PropertyRequirement.brokerage_id) == brokerage_id,
        col(PropertyRequirement.id) == requirement_id,
        col(PropertyRequirement.is_deleted).is_(False),
    )
    row = session.execute(statement).first()
    return RequirementSpecification(row[0], tuple(row[1] or ())) if row else None


def find_unit_specification(
    session: Session, brokerage_id: int, unit_id: int
) -> UnitSpecification | None:
    """삭제되지 않은 세대의 단지와 평형. 화면에서 사라진 세대는 조건을 만들지 않는다."""
    statement = select(col(PropertyUnit.complex_id), col(PropertyUnit.pyeong)).where(
        col(PropertyUnit.brokerage_id) == brokerage_id,
        col(PropertyUnit.id) == unit_id,
        col(PropertyUnit.is_deleted).is_(False),
    )
    row = session.execute(statement).first()
    return UnitSpecification(row[0], row[1]) if row else None


def list_requirement_complex_ids(
    session: Session, brokerage_id: int, requirement_id: int
) -> list[int]:
    """구입장이 지정한 희망 단지. 삭제된 단지는 빼서 살아 있는 조건만 남긴다."""
    statement = (
        select(col(PropertyRequirementComplex.complex_id))
        .join(
            PropertyComplex,
            (col(PropertyComplex.brokerage_id) == PropertyRequirementComplex.brokerage_id)
            & (col(PropertyComplex.id) == PropertyRequirementComplex.complex_id),
        )
        .where(
            col(PropertyRequirementComplex.brokerage_id) == brokerage_id,
            col(PropertyRequirementComplex.requirement_id) == requirement_id,
            col(PropertyComplex.is_deleted).is_(False),
        )
        .order_by(col(PropertyRequirementComplex.complex_id).asc())
    )
    return list(session.execute(statement).scalars().all())


class RequirementCandidateRow(NamedTuple):
    """구입장 후보 1건의 점수 계산 입력."""

    requirement_id: int
    max_budget_amount: int | None
    desired_pyeongs: tuple[Decimal, ...]
    received_at: date | None


def list_requirement_candidates(
    session: Session,
    brokerage_id: int,
    *,
    demand_types: Sequence[str],
    active_statuses: Sequence[str],
    budget_floor_amount: int | None,
    complex_id: int | None,
) -> list[RequirementCandidateRow]:
    """매물 앵커의 반대편 후보. 조건에 맞는 구입장만 돌려준다 (F3-SQ-01).

    포함·제외는 전부 SQL 조건이다. 사무소, 구입장 삭제, 인물 삭제, **거래 구분**, **활성
    업무 상태**, 예산 하한과 희망 단지가 조건이며 평형과 최신성은 점수로만 반영한다.

    `demand_types` 는 앵커 매물의 거래 유형과 호환되는 구입장 구분이다. 매매 매물에 전세
    손님이 붙거나 월세 매물에 매수 손님이 붙으면 안 된다. 비어 있으면 호환되는 구분이
    없다는 뜻이므로 후보도 없다.

    희망 단지를 하나도 지정하지 않은 구입장은 단지를 가리지 않는 손님이므로 포함한다.
    예산이 비어 있는 구입장도 포함한다. 예산 미기재는 "못 산다"가 아니라 "아직 모른다"이며,
    금액을 모르는 후보는 가격 근접도 0 으로 뒤에 밀린다.
    """
    if not demand_types:
        return []

    conditions: list[Any] = [
        col(PropertyRequirement.brokerage_id) == brokerage_id,
        col(PropertyRequirement.is_deleted).is_(False),
        col(Party.is_deleted).is_(False),
        col(PropertyRequirement.demand_type).in_(sorted(demand_types)),
        col(PropertyRequirement.status).in_(sorted(active_statuses)),
    ]
    if budget_floor_amount is not None:
        conditions.append(
            or_(
                col(PropertyRequirement.max_budget_amount).is_(None),
                col(PropertyRequirement.max_budget_amount) >= budget_floor_amount,
            )
        )
    if complex_id is not None:
        wants_any_complex = (
            ~select(literal(1))
            .where(
                col(PropertyRequirementComplex.brokerage_id) == brokerage_id,
                col(PropertyRequirementComplex.requirement_id) == PropertyRequirement.id,
            )
            .exists()
        )
        wants_this_complex = (
            select(literal(1))
            .where(
                col(PropertyRequirementComplex.brokerage_id) == brokerage_id,
                col(PropertyRequirementComplex.requirement_id) == PropertyRequirement.id,
                col(PropertyRequirementComplex.complex_id) == complex_id,
            )
            .exists()
        )
        conditions.append(or_(wants_any_complex, wants_this_complex))

    statement = (
        select(
            col(PropertyRequirement.id),
            col(PropertyRequirement.max_budget_amount),
            col(PropertyRequirement.desired_pyeongs),
            col(PropertyRequirement.received_at),
        )
        .join(
            Party,
            (col(Party.brokerage_id) == PropertyRequirement.brokerage_id)
            & (col(Party.id) == PropertyRequirement.party_id),
        )
        .where(*conditions)
        .order_by(col(PropertyRequirement.id).asc())
    )
    return [
        RequirementCandidateRow(row[0], row[1], tuple(row[2] or ()), row[3])
        for row in session.execute(statement).all()
    ]


class ListingCandidateRow(NamedTuple):
    """매물 후보 1건의 점수 계산 입력.

    `price_amount` 는 요청한 거래 유형의 주 금액이다. 월세는 보증금이고 월 차임은
    `monthly_amount` 에 따로 담는다. 두 축을 하나로 접지 않는다.
    """

    listing_id: int
    price_amount: int | None
    monthly_amount: int | None
    pyeong: Decimal | None
    received_at: date | None


# 거래 유형별로 어떤 플래그와 어떤 금액 컬럼을 보는지. 여기 한 곳에만 둔다.
# 매매가가 있다고 전세 손님의 후보가 되면 안 되므로 유형을 섞어 coalesce 하지 않는다.
_LISTING_TRADE_COLUMNS: dict[str, tuple[Any, Any, Any]] = {
    "SALE": (PropertyListing.is_sale_available, PropertyListing.sale_price, None),
    "JEONSE": (
        PropertyListing.is_jeonse_available,
        PropertyListing.jeonse_deposit_amount,
        None,
    ),
    "MONTHLY_RENT": (
        PropertyListing.is_monthly_rent_available,
        PropertyListing.monthly_rent_deposit_amount,
        PropertyListing.monthly_rent_amount,
    ),
}


def list_listing_candidates(
    session: Session,
    brokerage_id: int,
    *,
    price_kind: str | None,
    active_statuses: Sequence[str],
    price_ceiling_amount: int | None,
    complex_ids: Sequence[int],
) -> list[ListingCandidateRow]:
    """구입장 앵커의 반대편 후보. 조건에 맞는 매물만 돌려준다 (F3-SQ-01).

    `price_kind` 는 앵커 구입장의 `demand_type` 과 호환되는 매물 거래 유형이다. 그 유형의
    **거래 가능 플래그가 참인 매물만** 후보이며 금액도 그 유형의 컬럼만 본다. 플래그가
    거짓인 채 남아 있는 과거 금액을 후보 가격으로 쓰지 않는다. 호환되는 유형이 없으면
    후보도 없다.

    F1 매물 조회와 같은 범위를 본다. **부모 세대 삭제 여부까지** 본다. 세대 소프트 삭제는
    딸린 매물 행을 건드리지 않아 매물 행만 보면 화면에 없는 세대의 매물이 후보로 올라온다.

    희망 단지를 지정한 구입장이면 그 단지의 매물만 본다. 지정하지 않았으면 단지를 가리지
    않는다.
    """
    trade = _LISTING_TRADE_COLUMNS.get(price_kind or "")
    if trade is None:
        return []
    available, amount_column, monthly_column = trade

    price = col(amount_column)
    conditions: list[Any] = [
        col(PropertyListing.brokerage_id) == brokerage_id,
        col(PropertyListing.is_deleted).is_(False),
        col(PropertyUnit.is_deleted).is_(False),
        col(available).is_(True),
        col(PropertyListing.status).in_(sorted(active_statuses)),
    ]
    if price_ceiling_amount is not None:
        # 보증금·매매가 축만 비교한다. 구입장에는 월 차임에 대응하는 예산 축이 없다.
        conditions.append(or_(price.is_(None), price <= price_ceiling_amount))
    if complex_ids:
        conditions.append(col(PropertyUnit.complex_id).in_(list(complex_ids)))

    statement = (
        select(PropertyListing, col(PropertyUnit.pyeong))
        .join(
            PropertyUnit,
            (col(PropertyUnit.brokerage_id) == PropertyListing.brokerage_id)
            & (col(PropertyUnit.id) == PropertyListing.unit_id),
        )
        .where(*conditions)
        .order_by(col(PropertyListing.id).asc())
    )
    # 금액은 위 매핑이 정한 컬럼에서만 읽는다. 조회 조건과 같은 한 곳을 쓴다.
    return [
        ListingCandidateRow(
            listing_id=listing.id or 0,
            price_amount=getattr(listing, amount_column.key),
            monthly_amount=(
                getattr(listing, monthly_column.key) if monthly_column is not None else None
            ),
            pyeong=pyeong,
            received_at=listing.received_at,
        )
        for listing, pyeong in session.execute(statement).all()
    ]


def find_position_card_for_target(
    session: Session,
    brokerage_id: int,
    *,
    position_analysis_id: int,
    negotiation_side: str,
    listing_id: int | None,
    requirement_id: int | None,
) -> NegotiationPositionAnalysis | None:
    """실행이 기록한 카드 ID 를 다시 확인한다. 사무소·측면·대상·활성 여부를 함께 본다."""
    statement = select(NegotiationPositionAnalysis).where(
        col(NegotiationPositionAnalysis.brokerage_id) == brokerage_id,
        col(NegotiationPositionAnalysis.id) == position_analysis_id,
        col(NegotiationPositionAnalysis.negotiation_side) == negotiation_side,
        col(NegotiationPositionAnalysis.listing_id).is_not_distinct_from(listing_id),
        col(NegotiationPositionAnalysis.requirement_id).is_not_distinct_from(requirement_id),
        col(NegotiationPositionAnalysis.invalidated_at).is_(None),
    )
    return session.execute(statement).scalars().first()


def find_match_evaluation_for_run(
    session: Session, brokerage_id: int, agent_run_id: int
) -> MatchEvaluation | None:
    """이 실행의 판정 헤더. 재선점으로 같은 단계가 다시 돌 때 중복 생성을 막는다."""
    statement = select(MatchEvaluation).where(
        col(MatchEvaluation.brokerage_id) == brokerage_id,
        col(MatchEvaluation.agent_run_id) == agent_run_id,
    )
    return session.execute(statement).scalars().first()


def insert_match_evaluation(session: Session, header: MatchEvaluation) -> MatchEvaluation:
    session.add(header)
    session.flush()
    return header


def update_match_evaluation_selection(
    session: Session,
    brokerage_id: int,
    match_evaluation_id: int,
    *,
    anchor_position_analysis_id: int,
    candidate_count: int,
    candidate_selection_snapshot: dict[str, Any],
) -> int:
    """재선점으로 후보를 다시 뽑았을 때 헤더를 갱신한다. 바꾼 행 수를 돌려준다."""
    statement = (
        update(MatchEvaluation)
        .where(
            col(MatchEvaluation.brokerage_id) == brokerage_id,
            col(MatchEvaluation.id) == match_evaluation_id,
        )
        .values(
            anchor_position_analysis_id=anchor_position_analysis_id,
            candidate_count=candidate_count,
            candidate_selection_snapshot=candidate_selection_snapshot,
        )
        .execution_options(synchronize_session=False)
    )
    return cast(CursorResult[Any], session.execute(statement)).rowcount


def update_match_evaluation_snapshot(
    session: Session,
    brokerage_id: int,
    match_evaluation_id: int,
    *,
    candidate_selection_snapshot: dict[str, Any],
) -> int:
    """후보 snapshot 만 갱신한다. 후보 카드 ID 를 붙일 때 쓴다. 바꾼 행 수를 돌려준다."""
    statement = (
        update(MatchEvaluation)
        .where(
            col(MatchEvaluation.brokerage_id) == brokerage_id,
            col(MatchEvaluation.id) == match_evaluation_id,
        )
        .values(candidate_selection_snapshot=candidate_selection_snapshot)
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
