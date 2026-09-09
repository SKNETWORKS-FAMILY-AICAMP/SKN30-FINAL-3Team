from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, NamedTuple

from sqlalchemy import and_, func, literal, or_
from sqlmodel import Session, col, select

from core.errors import NotFoundError
from domain.agent_execution.models import (
    AnchorType,
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


class InteractionSummary(NamedTuple):
    """상담 로그 집합의 신원. 시각 하나로는 과거 로그 추가와 무효화를 구분하지 못한다."""

    interaction_count: int
    last_interaction_at: datetime | None
    max_interaction_id: int | None


# 로그 포함 정책이 바뀌면 올린다. scope identity 에 들어가 캐시와 fencing 이 함께 갱신된다.
INTERACTION_SCOPE_CONTRACT_VERSION = "interaction-scope:v3"


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
        # 직접 연결은 대상만 확정한다. 명시된 당사자는 허용 범위에 속해야 한다.
        # 당사자 미기재 직접 로그는 구입장 경로와 같이 허용한다.
        explicit_listing = (
            and_(
                col(ClientInteraction.listing_id) == scope.listing_id,
                or_(col(ClientInteraction.party_id).is_(None), is_allowed_party),
            )
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
