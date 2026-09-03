"""일정·할 일 대상 조회.

일곱 개의 날짜 원천을 ``UNION ALL``로 합친 뒤 DB에서 정렬·페이지를 자른다. 원천별로 따로 읽어
파이썬에서 합치면 전체를 메모리에 올려야 총 건수와 페이지가 맞는다.

날짜가 그대로 저장된 원천과, 마지막 접촉·접수일에 주기를 더해 만드는 원천이 섞여 있다. 뒤쪽은
`timestamptz`를 사무소 시간대의 날짜로 옮긴 뒤 더한다. 서버 시간대에 맡기면 배포 환경에 따라
하루가 밀린다.

만기 세 갈래의 ``WHERE``는 migration 002·009가 만든 부분 인덱스 조건과 같은 모양으로 둔다.
조건이 어긋나면 인덱스를 두고도 전체 스캔이 된다. 규칙으로 만드는 갈래와
``property_requirement.desired_move_in_date``에는 아직 전용 인덱스가 없다.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import (
    BigInteger,
    Date,
    String,
    Subquery,
    cast,
    func,
    literal,
    null,
    select,
    union_all,
)
from sqlmodel import Session, col

from domain.property_ledger.models import (
    Party,
    PropertyComplex,
    PropertyListing,
    PropertyRequirement,
    PropertyUnit,
)
from domain.property_ledger.repository import Page
from domain.time_keeper.models import (
    BUSINESS_TIMEZONE,
    AgendaCategory,
    AgendaRow,
    AgendaWindow,
    RequirementAgendaDetail,
    UnitAgendaDetail,
)

# 종료된 구입 의뢰와 내려간 매물의 일정은 알리지 않는다. F1이 아직 상태 값 목록을 확정하지
# 않았으므로 서버가 신규 저장에 쓰는 기본값만 "진행 중"으로 본다. F3 후보 추출의 판단과 같은
# 근거이며 (`domain/agent_execution/candidates.py`) 값 목록이 확정되면 함께 고친다.
ACTIVE_REQUIREMENT_STATUSES = frozenset({"ACTIVE"})
ACTIVE_LISTING_STATUSES = frozenset({"RECEIVED"})


def _category(category: AgendaCategory) -> Any:
    """UNION의 첫 분기가 컬럼 타입을 정하므로 문자열 상수에 타입을 명시한다."""
    return cast(literal(category.value), String).label("category")


def _business_date(timestamp_column: Any) -> Any:
    """`timestamptz`를 사무소 시간대의 달력 날짜로 옮긴다."""
    return cast(func.timezone(BUSINESS_TIMEZONE, timestamp_column), Date)


def _member(
    category: AgendaCategory,
    due: Any,
    *,
    unit_id: Any,
    listing_id: Any,
    requirement_id: Any,
    conditions: Sequence[Any],
    window: AgendaWindow,
) -> Any:
    return select(
        _category(category),
        due.label("due_date"),
        unit_id.label("unit_id"),
        listing_id.label("listing_id"),
        requirement_id.label("requirement_id"),
    ).where(*conditions, due.between(window.earliest, window.latest))


def _no_id() -> Any:
    return cast(null(), BigInteger)


def _unit_members(brokerage_id: int, window: AgendaWindow) -> list[Any]:
    live_unit = [
        col(PropertyUnit.brokerage_id) == brokerage_id,
        col(PropertyUnit.is_deleted).is_(False),
    ]
    expiry = col(PropertyUnit.tenancy_expiry_date)
    last_contact = col(PropertyUnit.last_contact_at)
    return [
        _member(
            AgendaCategory.TENANCY_EXPIRY,
            expiry,
            unit_id=col(PropertyUnit.id),
            listing_id=_no_id(),
            requirement_id=_no_id(),
            conditions=[*live_unit, expiry.is_not(None)],
            window=window,
        ),
        _member(
            AgendaCategory.LISTING_RECONTACT,
            _business_date(last_contact) + window.recontact_days,
            unit_id=col(PropertyUnit.id),
            listing_id=_no_id(),
            requirement_id=_no_id(),
            conditions=[*live_unit, last_contact.is_not(None)],
            window=window,
        ),
    ]


def _listing_members(brokerage_id: int, window: AgendaWindow) -> list[Any]:
    received = col(PropertyListing.received_at)
    return [
        _member(
            AgendaCategory.LISTING_REVALIDATION,
            received + window.revalidation_days,
            unit_id=col(PropertyListing.unit_id),
            listing_id=col(PropertyListing.id),
            requirement_id=_no_id(),
            conditions=[
                col(PropertyListing.brokerage_id) == brokerage_id,
                col(PropertyListing.is_deleted).is_(False),
                col(PropertyListing.status).in_(sorted(ACTIVE_LISTING_STATUSES)),
                received.is_not(None),
            ],
            window=window,
        )
    ]


def _requirement_members(brokerage_id: int, window: AgendaWindow) -> list[Any]:
    live_requirement = [
        col(PropertyRequirement.brokerage_id) == brokerage_id,
        col(PropertyRequirement.is_deleted).is_(False),
        col(PropertyRequirement.status).in_(sorted(ACTIVE_REQUIREMENT_STATUSES)),
    ]
    last_contact = col(PropertyRequirement.last_contact_at)
    client_tenancy = col(PropertyRequirement.current_tenancy_expiry_date)
    stored: list[tuple[AgendaCategory, Any]] = [
        (AgendaCategory.CLIENT_TENANCY_EXPIRY, client_tenancy),
        (AgendaCategory.REQUEST_EXPIRY, col(PropertyRequirement.request_expiry_date)),
        (AgendaCategory.MOVE_IN, col(PropertyRequirement.desired_move_in_date)),
    ]
    members = [
        _member(
            category,
            column,
            unit_id=_no_id(),
            listing_id=_no_id(),
            requirement_id=col(PropertyRequirement.id),
            conditions=[*live_requirement, column.is_not(None)],
            window=window,
        )
        for category, column in stored
    ]
    members.append(
        _member(
            AgendaCategory.CLIENT_RECONTACT,
            _business_date(last_contact) + window.recontact_days,
            unit_id=_no_id(),
            listing_id=_no_id(),
            requirement_id=col(PropertyRequirement.id),
            conditions=[*live_requirement, last_contact.is_not(None)],
            window=window,
        )
    )
    return members


def agenda_union(brokerage_id: int, window: AgendaWindow) -> Subquery:
    return union_all(
        *_unit_members(brokerage_id, window),
        *_listing_members(brokerage_id, window),
        *_requirement_members(brokerage_id, window),
    ).subquery("time_keeper_agenda")


def count_agenda(session: Session, brokerage_id: int, window: AgendaWindow) -> int:
    combined = agenda_union(brokerage_id, window)
    total = session.execute(select(func.count()).select_from(combined)).scalar_one()
    return int(total)


def count_agenda_by_category(
    session: Session, brokerage_id: int, window: AgendaWindow
) -> list[tuple[AgendaCategory, int]]:
    """창 안에 실제로 존재하는 종류와 건수. 0건인 종류는 행 자체가 나오지 않는다.

    종류별 상한을 적용하기 전의 값이다. 화면이 "임대차 만기 2건"처럼 참인 숫자를 쓰고, 상한에
    걸려 잘린 나머지를 알릴 수 있어야 한다.
    """
    combined = agenda_union(brokerage_id, window)
    statement = (
        select(combined.c.category, func.count().label("total"))
        .group_by(combined.c.category)
        .order_by(combined.c.category.asc())
    )
    return [(AgendaCategory(row.category), int(row.total)) for row in session.execute(statement)]


def _ordering(source: Any) -> list[Any]:
    """같은 날짜에 걸리는 행이 흔하므로 종류와 식별자까지 정렬에 넣는다.

    정렬이 흔들리면 페이지를 넘길 때 같은 행이 다시 나오거나 건너뛴다.
    """
    return [
        source.c.due_date.asc(),
        source.c.category.asc(),
        source.c.unit_id.asc().nullslast(),
        source.c.listing_id.asc().nullslast(),
        source.c.requirement_id.asc().nullslast(),
    ]


def list_agenda(
    session: Session, brokerage_id: int, window: AgendaWindow, page: Page
) -> list[AgendaRow]:
    """종류마다 앞에서 몇 건씩 떼어 기한이 이른 순으로 한 페이지를 읽는다.

    상한을 전체에만 걸면 임박한 한 종류가 지면을 다 먹고 나머지 종류는 그날 아예 보이지 않는다.
    ``ROW_NUMBER``로 종류 안에서 순위를 매긴 뒤 잘라 해당되는 종류가 모두 드러나게 한다.
    """
    combined = agenda_union(brokerage_id, window)
    ranked = select(
        combined.c.category,
        combined.c.due_date,
        combined.c.unit_id,
        combined.c.listing_id,
        combined.c.requirement_id,
        func.row_number()
        .over(partition_by=combined.c.category, order_by=_ordering(combined))
        .label("category_rank"),
    ).subquery("time_keeper_agenda_ranked")
    statement = (
        select(ranked)
        .where(ranked.c.category_rank <= window.per_category_limit)
        .order_by(*_ordering(ranked))
        .limit(page.limit)
        .offset(page.offset)
    )
    return [
        AgendaRow(
            category=AgendaCategory(row.category),
            due_date=row.due_date,
            unit_id=row.unit_id,
            listing_id=row.listing_id,
            requirement_id=row.requirement_id,
        )
        for row in session.execute(statement).all()
    ]


def load_unit_details(
    session: Session, brokerage_id: int, unit_ids: Sequence[int]
) -> dict[int, UnitAgendaDetail]:
    """페이지에 실린 세대의 표시값을 한 번에 읽는다."""
    if not unit_ids:
        return {}
    statement = (
        select(PropertyUnit, PropertyComplex)
        .join(
            PropertyComplex,
            (col(PropertyComplex.brokerage_id) == PropertyUnit.brokerage_id)
            & (col(PropertyComplex.id) == PropertyUnit.complex_id),
        )
        .where(
            col(PropertyUnit.brokerage_id) == brokerage_id,
            col(PropertyUnit.id).in_(list(unit_ids)),
            col(PropertyUnit.is_deleted).is_(False),
        )
    )
    return {
        unit.id or 0: UnitAgendaDetail(
            unit_id=unit.id or 0,
            complex_name=complex_row.name,
            building_number=unit.building_number,
            unit_number=unit.unit_number,
            tenancy_status=unit.tenancy_status,
            assigned_user_id=unit.assigned_user_id,
            last_contact_at=unit.last_contact_at,
        )
        for unit, complex_row in session.execute(statement).all()
    }


def load_requirement_details(
    session: Session, brokerage_id: int, requirement_ids: Sequence[int]
) -> dict[int, RequirementAgendaDetail]:
    """페이지에 실린 구입장 행의 표시값을 한 번에 읽는다."""
    if not requirement_ids:
        return {}
    statement = select(PropertyRequirement).where(
        col(PropertyRequirement.brokerage_id) == brokerage_id,
        col(PropertyRequirement.id).in_(list(requirement_ids)),
        col(PropertyRequirement.is_deleted).is_(False),
    )
    return {
        requirement.id or 0: RequirementAgendaDetail(
            requirement_id=requirement.id or 0,
            party_id=requirement.party_id,
            demand_type=requirement.demand_type,
            status=requirement.status,
            assigned_user_id=requirement.assigned_user_id,
            last_contact_at=requirement.last_contact_at,
        )
        for requirement in session.execute(statement).scalars().all()
    }


def load_parties(session: Session, brokerage_id: int, party_ids: Sequence[int]) -> dict[int, Party]:
    """구입장 손님 본인. 세대 쪽 인물은 장부의 관계 조회가 이미 인물을 함께 돌려준다."""
    if not party_ids:
        return {}
    statement = select(Party).where(
        col(Party.brokerage_id) == brokerage_id,
        col(Party.id).in_(list(party_ids)),
        col(Party.is_deleted).is_(False),
    )
    return {party.id or 0: party for party in session.execute(statement).scalars().all()}
