"""F1 장부를 AI 요청 DTO로 옮기는 조립 단계.

여기서 하는 일은 넷이다. 대리 측면이 읽어도 되는 로그 범위를 정하고, 장부 사실을 읽고,
개인정보를 가리고, 날짜를 미리 계산한다. AI는 이 넷을 하지 않는다. 조립 결과는 프레임워크
중립 DTO라 이 모듈 밖으로 ORM 행이 나가지 않는다.

순서가 중요하다. **로그를 먼저 고르고 그 로그의 당사자까지 secret 에 넣은 뒤** 마스킹한다.
현재 관계자만 모으면 과거 소유자처럼 관계가 끝난 당사자의 이름이 원문에 남는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from brokerage_ai.f3 import (
    ConsultationLogInput,
    DateSignals,
    ListingAnchorContext,
    NegotiationSide,
    PartyRoleContext,
    PositionCardGenerationRequest,
    RequirementAnchorContext,
    SourceIdentity,
)
from sqlmodel import Session

from core.errors import NotFoundError
from domain.agent_execution import repository
from domain.agent_execution.masking import mask_text
from domain.agent_execution.models import AnchorType
from domain.property_ledger.models import ClientInteraction

TARGET_LABEL_MAX_LENGTH = 200


@dataclass(frozen=True)
class AnchorSnapshot:
    """조립 결과. 요청 DTO와 그 요청을 만들 때 쓴 범위·식별값을 함께 들고 있다.

    `secrets`는 모델 출력 검사에 다시 쓴다. 모델이 가려진 값을 되살려 내면 저장을 막아야
    하는데, 그러려면 무엇을 가렸는지 알아야 한다. 이 값은 요청·결과·DB·로그에 저장하지 않고
    한 번의 실행 안에서만 메모리에 둔다.
    """

    request: PositionCardGenerationRequest
    scope: repository.InteractionScope
    secrets: tuple[str, ...]


def _days_until(target: date | None, as_of: date) -> int | None:
    """남은 일수. 이미 지난 기한은 음수가 된다."""
    return None if target is None else (target - as_of).days


def _days_since(moment: datetime | None, as_of: datetime) -> int | None:
    return None if moment is None else (as_of.date() - moment.astimezone(UTC).date()).days


def _days_since_date(target: date | None, as_of: date) -> int | None:
    return None if target is None else (as_of - target).days


def _hard_deadline_candidate(*candidates: date | None) -> date | None:
    """직접 확인 가능한 날짜 중 가장 이른 것.

    영업일이나 준비 기간을 임의로 빼지 않는다. 승인되지 않은 기간을 끼워 넣으면 근거 없는
    마감일이 만들어진다.
    """
    known = [candidate for candidate in candidates if candidate is not None]
    return min(known) if known else None


def _clip(label: str) -> str:
    """DB `VARCHAR(200)` 을 넘지 않게 결정적으로 자른다."""
    return (
        label
        if len(label) <= TARGET_LABEL_MAX_LENGTH
        else label[: TARGET_LABEL_MAX_LENGTH - 1] + "…"
    )


def _masked_logs(
    interactions: list[ClientInteraction], secrets: list[str]
) -> tuple[ConsultationLogInput, ...]:
    return tuple(
        ConsultationLogInput(
            interaction_id=interaction.id or 0,
            interaction_at=interaction.interaction_at or datetime.now(UTC),
            channel=interaction.interaction_channel,
            counterparty_role=interaction.counterparty_role,
            interaction_result=interaction.interaction_result,
            masked_content=mask_text(interaction.interaction_content, secrets) or "",
        )
        for interaction in interactions
    )


def _source_identity(data_version: int, logs: tuple[ConsultationLogInput, ...]) -> SourceIdentity:
    """전달하는 로그 자체에서 신원을 만든다. 별도로 센 값과 어긋날 수 없다."""
    if not logs:
        return SourceIdentity(data_version=data_version, interaction_count=0)
    return SourceIdentity(
        data_version=data_version,
        interaction_count=len(logs),
        last_interaction_at=max(log.interaction_at for log in logs),
        max_interaction_id=max(log.interaction_id for log in logs),
    )


def _user_secrets(session: Session, brokerage_id: int, user_ids: list[int | None]) -> list[str]:
    return repository.list_user_identifiers(session, brokerage_id, user_ids)


def _listing_snapshot(
    session: Session,
    brokerage_id: int,
    listing_id: int,
    as_of: datetime,
    requested_by: int | None,
) -> AnchorSnapshot:
    found = repository.find_listing_snapshot(session, brokerage_id, listing_id)
    if found is None:
        raise NotFoundError("property listing is not found")
    listing, unit, complex_row = found

    roles = repository.list_current_unit_party_roles(session, brokerage_id, unit.id or 0)
    # 범위는 저장 단계와 같은 함수로 만든다. 여기서 따로 조립하면 두 단계가 조용히 갈라진다.
    scope = repository.build_interaction_scope(
        session, brokerage_id, AnchorType.LISTING, listing.id or 0
    )
    interactions = repository.list_scoped_interactions(session, scope)
    allowed = set(scope.allowed_party_ids)

    # 실제로 고른 로그의 당사자까지 포함해야 관계가 끝난 인물의 이름도 가려진다.
    log_party_ids = {
        interaction.party_id for interaction in interactions if interaction.party_id is not None
    }
    secrets = [
        *repository.list_party_identifiers(session, brokerage_id, sorted(allowed | log_party_ids)),
        *_user_secrets(
            session,
            brokerage_id,
            [
                requested_by,
                listing.assigned_user_id,
                unit.assigned_user_id,
                *(interaction.created_by for interaction in interactions),
                *(interaction.approved_by for interaction in interactions),
            ],
        ),
    ]
    logs = _masked_logs(interactions, secrets)

    anchor = ListingAnchorContext(
        listing_id=listing.id or 0,
        unit_id=unit.id or 0,
        listing_status=listing.status,
        received_at=listing.received_at,
        is_sale_available=listing.is_sale_available,
        sale_price=listing.sale_price,
        is_jeonse_available=listing.is_jeonse_available,
        jeonse_deposit_amount=listing.jeonse_deposit_amount,
        is_monthly_rent_available=listing.is_monthly_rent_available,
        monthly_rent_deposit_amount=listing.monthly_rent_deposit_amount,
        monthly_rent_amount=listing.monthly_rent_amount,
        price_raw_text=mask_text(listing.price_raw_text, secrets),
        handover_condition=mask_text(listing.handover_condition, secrets),
        complex_name=complex_row.name,
        building_number=unit.building_number,
        unit_number=unit.unit_number,
        floor_number=unit.floor_number,
        orientation=unit.orientation,
        pyeong=unit.pyeong,
        exclusive_area_sqm=unit.exclusive_area_sqm,
        supply_area_sqm=unit.supply_area_sqm,
        unit_type=unit.unit_type,
        lifecycle_status=unit.lifecycle_status,
        tenancy_status=unit.tenancy_status,
        current_deposit_amount=unit.current_deposit_amount,
        current_monthly_rent_amount=unit.current_monthly_rent_amount,
        tenancy_expiry_date=unit.tenancy_expiry_date,
        tenancy_raw_text=mask_text(unit.tenancy_raw_text, secrets),
        # 순서가 의미 없는 집합이라 명시적으로 정렬한다. 조회 순서가 달라져도 같은 입력이면
        # 같은 프롬프트와 같은 지문이 나와야 한다.
        party_roles=tuple(
            sorted(
                (
                    PartyRoleContext(
                        role=role.role, is_primary=role.is_primary, is_co_owner=role.is_co_owner
                    )
                    for role in roles
                ),
                key=lambda item: (item.role, item.is_primary, item.is_co_owner),
            )
        ),
        client_party_role=next(
            (role.role for role in roles if role.party_id == listing.client_party_id), None
        ),
    )
    signals = DateSignals(
        as_of=as_of,
        days_until_tenancy_expiry=_days_until(unit.tenancy_expiry_date, as_of.date()),
        days_since_last_contact=_days_since(unit.last_contact_at, as_of),
        days_since_received=_days_since_date(listing.received_at, as_of.date()),
        hard_deadline_candidate=_hard_deadline_candidate(unit.tenancy_expiry_date),
    )
    request = PositionCardGenerationRequest(
        negotiation_side=NegotiationSide.LISTING,
        anchor_id=listing.id or 0,
        target_label=listing_target_label(complex_row.name, unit.building_number, unit.unit_number),
        source=_source_identity(listing.row_version, logs),
        anchor=anchor,
        date_signals=signals,
        consultation_logs=logs,
    )
    return AnchorSnapshot(request=request, scope=scope, secrets=tuple(secrets))


def listing_target_label(
    complex_name: str | None, building_number: str | None, unit_number: str
) -> str:
    """매물 카드의 화면 라벨. 이미 계약에 실린 구조화 값만 쓴다.

    성명과 연락처는 넣지 않는다. 단지·동·호는 인물이 아니라 부동산을 가리킨다.
    """
    parts = [part for part in (complex_name, building_number and f"{building_number}동") if part]
    parts.append(f"{unit_number}호")
    return _clip(" ".join(parts))


def requirement_target_label(requirement_id: int) -> str:
    """구입장 카드의 화면 라벨. 손님 이름 대신 안정적인 비식별 값을 쓴다."""
    return _clip(f"구입장 #{requirement_id}")


def _requirement_snapshot(
    session: Session,
    brokerage_id: int,
    requirement_id: int,
    as_of: datetime,
    requested_by: int | None,
) -> AnchorSnapshot:
    found = repository.find_requirement_anchor(session, brokerage_id, requirement_id)
    if found is None:
        raise NotFoundError("property requirement is not found")

    scope = repository.build_interaction_scope(
        session, brokerage_id, AnchorType.REQUIREMENT, found.id or 0
    )
    interactions = repository.list_scoped_interactions(session, scope)
    allowed = set(scope.allowed_party_ids)

    log_party_ids = {
        interaction.party_id for interaction in interactions if interaction.party_id is not None
    }
    secrets = [
        *repository.list_party_identifiers(session, brokerage_id, sorted(allowed | log_party_ids)),
        *_user_secrets(
            session,
            brokerage_id,
            [
                requested_by,
                found.assigned_user_id,
                *(interaction.created_by for interaction in interactions),
                *(interaction.approved_by for interaction in interactions),
            ],
        ),
    ]
    logs = _masked_logs(interactions, secrets)

    anchor = RequirementAnchorContext(
        requirement_id=found.id or 0,
        demand_type=found.demand_type,
        status=found.status,
        received_at=found.received_at,
        classification=found.classification,
        workflow_stage=found.workflow_stage,
        min_budget_amount=found.min_budget_amount,
        max_budget_amount=found.max_budget_amount,
        budget_raw_text=mask_text(found.budget_raw_text, secrets),
        desired_pyeongs=tuple(found.desired_pyeongs or ()),
        min_area_sqm=found.min_area_sqm,
        max_area_sqm=found.max_area_sqm,
        area_requirement_raw_text=mask_text(found.area_requirement_raw_text, secrets),
        desired_complex_names=tuple(
            repository.list_requirement_complex_names(session, brokerage_id, found.id or 0)
        ),
        desired_move_in_date=found.desired_move_in_date,
        move_in_date_raw_text=mask_text(found.move_in_date_raw_text, secrets),
        request_expiry_date=found.request_expiry_date,
        current_tenancy_expiry_date=found.current_tenancy_expiry_date,
        has_co_broker=found.co_broker_party_id is not None,
    )
    signals = DateSignals(
        as_of=as_of,
        days_until_desired_move_in=_days_until(found.desired_move_in_date, as_of.date()),
        days_until_request_expiry=_days_until(found.request_expiry_date, as_of.date()),
        days_until_tenancy_expiry=_days_until(found.current_tenancy_expiry_date, as_of.date()),
        days_since_last_contact=_days_since(found.last_contact_at, as_of),
        days_since_received=_days_since_date(found.received_at, as_of.date()),
        hard_deadline_candidate=_hard_deadline_candidate(
            found.desired_move_in_date, found.request_expiry_date, found.current_tenancy_expiry_date
        ),
    )
    request = PositionCardGenerationRequest(
        negotiation_side=NegotiationSide.REQUIREMENT,
        anchor_id=found.id or 0,
        target_label=requirement_target_label(found.id or 0),
        source=_source_identity(found.row_version, logs),
        anchor=anchor,
        date_signals=signals,
        consultation_logs=logs,
    )
    return AnchorSnapshot(request=request, scope=scope, secrets=tuple(secrets))


def build_anchor_snapshot(
    session: Session,
    brokerage_id: int,
    anchor_type: AnchorType,
    anchor_id: int,
    *,
    as_of: datetime,
    requested_by: int | None,
) -> AnchorSnapshot:
    """앵커 한쪽의 장부·로그·날짜 신호를 AI 요청으로 조립한다.

    기준 시각은 호출자가 한 번 정해서 넘긴다. 신호마다 시계를 다시 읽으면 같은 요청 안에서
    날짜가 어긋난다. `requested_by`는 그 사용자의 식별값을 가리기 위해서만 쓰이며 AI 요청
    DTO에는 들어가지 않는다.
    """
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")

    # 날짜 bucket과 파생 신호가 같은 기준을 써야 한다. 같은 순간을 KST로 넘겼다고
    # `days_until`이 하루 줄면 같은 cache key가 서로 다른 실제 AI 요청을 가리키게 된다.
    normalized_as_of = as_of.astimezone(UTC)
    if anchor_type is AnchorType.LISTING:
        return _listing_snapshot(session, brokerage_id, anchor_id, normalized_as_of, requested_by)
    return _requirement_snapshot(session, brokerage_id, anchor_id, normalized_as_of, requested_by)


def current_source_identity(
    session: Session, scope: repository.InteractionScope, data_version: int
) -> SourceIdentity:
    """같은 범위로 현재 상담 로그 신원을 다시 계산한다.

    저장 직전 재검증이 조립 때와 다른 범위를 쓰면 반대편 로그가 늘어나도 못 보거나, 반대로
    바뀌지 않았는데 바뀐 것으로 오인한다.
    """
    summary = repository.summarize_scoped_interactions(session, scope)
    if summary.interaction_count == 0:
        return SourceIdentity(data_version=data_version, interaction_count=0)
    return SourceIdentity(
        data_version=data_version,
        interaction_count=summary.interaction_count,
        last_interaction_at=summary.last_interaction_at,
        max_interaction_id=summary.max_interaction_id,
    )
