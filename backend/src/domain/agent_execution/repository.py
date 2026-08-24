from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
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
    NegotiationPositionAnalysis,
    NegotiationPositionEvidence,
    NegotiationPositionPrice,
)
from domain.property_ledger import repository as ledger_repository
from domain.property_ledger.models import (
    ClientInteraction,
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
            col(AgentRun.status) == RUNNING_STATUS,
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
