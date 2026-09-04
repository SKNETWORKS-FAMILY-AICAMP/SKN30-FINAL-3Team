"""일정·할 일 목록 유스케이스.

장부를 바꾸지 않는 읽기 전용 조회다. 페이지를 먼저 자르고 그 페이지에 실린 대상의 인물과
연락처만 뒤이어 읽는다. 행마다 인물을 따로 조회하면 한 화면에 수십 번의 왕복이 생긴다.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from sqlmodel import Session

from domain.property_ledger import repository as ledger_repository
from domain.property_ledger.models import Party, PartyContact, PropertyUnitPartyRelation
from domain.property_ledger.repository import Page
from domain.time_keeper import repository
from domain.time_keeper.models import (
    DEFAULT_OVERDUE_DAYS,
    DEFAULT_PER_CATEGORY_LIMIT,
    DEFAULT_RECONTACT_DAYS,
    DEFAULT_REVALIDATION_DAYS,
    DEFAULT_WITHIN_DAYS,
    AgendaCategoryCount,
    AgendaContact,
    AgendaEntry,
    AgendaPage,
    AgendaRow,
    RequirementAgendaDetail,
    UnitAgendaDetail,
    build_window,
    days_until_due,
    today_in_business_timezone,
)

ContactsByParty = dict[int, list[PartyContact]]
RelationsByUnit = dict[int, list[tuple[PropertyUnitPartyRelation, Party]]]


def load_agenda(
    session: Session,
    brokerage_id: int,
    *,
    limit: int,
    offset: int,
    within_days: int = DEFAULT_WITHIN_DAYS,
    overdue_days: int = DEFAULT_OVERDUE_DAYS,
    recontact_days: int = DEFAULT_RECONTACT_DAYS,
    revalidation_days: int = DEFAULT_REVALIDATION_DAYS,
    per_category_limit: int = DEFAULT_PER_CATEGORY_LIMIT,
    as_of: date | None = None,
) -> AgendaPage:
    """기한이 다가온 일정과 할 일을 이른 순으로 한 페이지 돌려준다.

    ``as_of``는 테스트가 오늘을 고정하기 위한 입구다. 비워 두면 중개사무소 시간대의 오늘을 쓴다.
    """
    resolved_as_of = today_in_business_timezone() if as_of is None else as_of
    window = build_window(
        resolved_as_of,
        within_days,
        overdue_days,
        recontact_days=recontact_days,
        revalidation_days=revalidation_days,
        per_category_limit=per_category_limit,
    )
    page = Page(limit=limit, offset=offset)

    total = repository.count_agenda(session, brokerage_id, window)
    category_totals = repository.count_agenda_by_category(session, brokerage_id, window)
    rows = repository.list_agenda(session, brokerage_id, window, page)

    unit_ids = sorted({row.unit_id for row in rows if row.unit_id is not None})
    requirement_ids = sorted({row.requirement_id for row in rows if row.requirement_id is not None})

    units = repository.load_unit_details(session, brokerage_id, unit_ids)
    requirements = repository.load_requirement_details(session, brokerage_id, requirement_ids)

    relations = ledger_repository.list_unit_party_relations_for_units(
        session, brokerage_id, unit_ids
    )
    client_party_ids = {detail.party_id for detail in requirements.values()}
    parties = repository.load_parties(session, brokerage_id, sorted(client_party_ids))

    related_party_ids = {party.id or 0 for _, party in relations}
    contacts = _contacts_by_party(
        ledger_repository.list_party_contacts(
            session, brokerage_id, sorted(related_party_ids | client_party_ids)
        )
    )
    relations_by_unit = _relations_by_unit(relations)

    items: list[AgendaEntry] = []
    for row in rows:
        entry = _entry(
            row, resolved_as_of, units, requirements, parties, relations_by_unit, contacts
        )
        # 조회 사이에 다른 사용자가 대상을 지웠으면 건너뛴다. 이 경우에만 items가 total보다
        # 적어지며, 다음 요청에서 total도 함께 줄어든다.
        if entry is not None:
            items.append(entry)

    return AgendaPage(
        items=tuple(items),
        # 0건인 종류는 애초에 행이 없으므로 여기에도 실리지 않는다.
        categories=tuple(
            AgendaCategoryCount(category=category, total=count)
            for category, count in category_totals
        ),
        total=total,
        limit=page.limit,
        offset=page.offset,
        as_of=resolved_as_of,
        within_days=within_days,
        overdue_days=overdue_days,
        per_category_limit=per_category_limit,
    )


def _contacts_by_party(contacts: list[PartyContact]) -> ContactsByParty:
    grouped: ContactsByParty = defaultdict(list)
    for contact in contacts:
        grouped[contact.party_id].append(contact)
    return grouped


def _relations_by_unit(
    relations: list[tuple[PropertyUnitPartyRelation, Party]],
) -> RelationsByUnit:
    grouped: RelationsByUnit = defaultdict(list)
    for relation, party in relations:
        grouped[relation.unit_id].append((relation, party))
    return grouped


def _entry(
    row: AgendaRow,
    as_of: date,
    units: dict[int, UnitAgendaDetail],
    requirements: dict[int, RequirementAgendaDetail],
    parties: dict[int, Party],
    relations_by_unit: RelationsByUnit,
    contacts: ContactsByParty,
) -> AgendaEntry | None:
    remaining = days_until_due(row.due_date, as_of)

    if row.unit_id is not None:
        unit = units.get(row.unit_id)
        if unit is None:
            return None
        return AgendaEntry(
            category=row.category,
            due_date=row.due_date,
            days_until_due=remaining,
            unit_id=unit.unit_id,
            listing_id=row.listing_id,
            complex_name=unit.complex_name,
            building_number=unit.building_number,
            unit_number=unit.unit_number,
            tenancy_status=unit.tenancy_status,
            requirement_id=None,
            demand_type=None,
            requirement_status=None,
            assigned_user_id=unit.assigned_user_id,
            last_contact_at=unit.last_contact_at,
            contacts=tuple(
                AgendaContact(
                    role=relation.role,
                    is_primary=relation.is_primary,
                    party=party,
                    contacts=tuple(contacts.get(party.id or 0, [])),
                )
                for relation, party in relations_by_unit.get(unit.unit_id, [])
            ),
        )

    if row.requirement_id is None:  # pragma: no cover - union의 분기가 모두 비는 행은 없다
        return None
    requirement = requirements.get(row.requirement_id)
    if requirement is None:
        return None
    party = parties.get(requirement.party_id)
    return AgendaEntry(
        category=row.category,
        due_date=row.due_date,
        days_until_due=remaining,
        unit_id=None,
        listing_id=None,
        complex_name=None,
        building_number=None,
        unit_number=None,
        tenancy_status=None,
        requirement_id=requirement.requirement_id,
        demand_type=requirement.demand_type,
        requirement_status=requirement.status,
        assigned_user_id=requirement.assigned_user_id,
        last_contact_at=requirement.last_contact_at,
        # 구입장 행은 인물이 필수지만 그 인물만 따로 지워진 데이터를 만나도 일정 자체는 보여준다.
        contacts=()
        if party is None
        else (
            AgendaContact(
                role=None,
                is_primary=True,
                party=party,
                contacts=tuple(contacts.get(party.id or 0, [])),
            ),
        ),
    )
