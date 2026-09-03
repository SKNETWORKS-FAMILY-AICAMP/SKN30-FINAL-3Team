from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel

from api.schemas.property_ledger import PartySummary
from domain.time_keeper.models import (
    AgendaCategoryCount,
    AgendaContact,
    AgendaEntry,
    AgendaPage,
)


class AgendaContactResponse(BaseModel):
    """일정 한 건에 연락할 대상 한 명.

    인물 요약은 장부와 같은 ``PartySummary``를 쓴다. 목록에서 곧바로 연락으로 넘어가는 화면이
    인물마다 상세를 다시 부르지 않게 하려는 것이며, 노출 범위도 구입장 목록과 같다.
    """

    #: 세대 관계 역할(``LANDLORD``·``TENANT``). 구입장 손님 본인은 null이다.
    role: str | None
    is_primary: bool
    party: PartySummary

    @classmethod
    def from_domain(cls, contact: AgendaContact) -> AgendaContactResponse:
        return cls(
            role=contact.role,
            is_primary=contact.is_primary,
            party=PartySummary.from_domain(contact.party, list(contact.contacts)),
        )


class AgendaItemResponse(BaseModel):
    """일정 목록 한 행.

    세대에서 온 행은 구입장 필드가, 구입장에서 온 행은 세대 필드가 null이다. 어느 쪽인지는
    ``category``가 정한다. 표시 문자열은 서버가 만들지 않고 장부 목록과 같이 원본 값을 싣는다.

    ``category``는 문자열이며 앞으로 늘어난다. 계약과 일정 테이블이 생기면 계약 체결일, 지급일,
    임장일, 신고 기한이 같은 목록에 붙는다. 클라이언트는 모르는 값을 오류로 다루지 않는다.
    """

    category: str
    due_date: date
    #: 오늘이면 0, 이미 지났으면 음수.
    days_until_due: int
    unit_id: int | None
    listing_id: int | None
    complex_name: str | None
    building_number: str | None
    unit_number: str | None
    tenancy_status: str | None
    requirement_id: int | None
    demand_type: str | None
    requirement_status: str | None
    assigned_user_id: int | None
    last_contact_at: datetime | None
    contacts: list[AgendaContactResponse]

    @classmethod
    def from_domain(cls, entry: AgendaEntry) -> AgendaItemResponse:
        return cls(
            category=entry.category.value,
            due_date=entry.due_date,
            days_until_due=entry.days_until_due,
            unit_id=entry.unit_id,
            listing_id=entry.listing_id,
            complex_name=entry.complex_name,
            building_number=entry.building_number,
            unit_number=entry.unit_number,
            tenancy_status=entry.tenancy_status,
            requirement_id=entry.requirement_id,
            demand_type=entry.demand_type,
            requirement_status=entry.requirement_status,
            assigned_user_id=entry.assigned_user_id,
            last_contact_at=entry.last_contact_at,
            contacts=[AgendaContactResponse.from_domain(item) for item in entry.contacts],
        )


class AgendaCategorySummary(BaseModel):
    """창 안에 실제로 존재하는 종류와 건수.

    건수가 0인 종류는 이 목록에 아예 나오지 않는다. 화면은 여기 실린 종류만 그리므로 "해당되는
    내용이 있을 때만" 보여주는 규칙이 서버 응답만으로 지켜진다.

    ``total``은 종류별 상한을 적용하기 전의 참값이다. ``items``에 실린 건수보다 클 수 있고,
    그 차이가 곧 "외 N건"이다.
    """

    category: str
    total: int

    @classmethod
    def from_domain(cls, count: AgendaCategoryCount) -> AgendaCategorySummary:
        return cls(category=count.category.value, total=count.total)


class AgendaListResponse(BaseModel):
    """목록과 그 목록을 만든 조건.

    ``as_of``를 함께 싣는 이유는 D-day의 기준을 서버가 정하기 때문이다. 브라우저가 자기 시계로
    다시 계산하면 자정 근처에서 서버가 보낸 ``days_until_due``와 어긋난다.
    """

    items: list[AgendaItemResponse]
    #: 건수가 0인 종류는 실리지 않는다.
    categories: list[AgendaCategorySummary]
    total: int
    limit: int
    offset: int
    as_of: date
    within_days: int
    overdue_days: int
    per_category_limit: int

    @classmethod
    def from_domain(cls, page: AgendaPage) -> AgendaListResponse:
        return cls(
            items=[AgendaItemResponse.from_domain(entry) for entry in page.items],
            categories=[AgendaCategorySummary.from_domain(count) for count in page.categories],
            total=page.total,
            limit=page.limit,
            offset=page.offset,
            as_of=page.as_of,
            within_days=page.within_days,
            overdue_days=page.overdue_days,
            per_category_limit=page.per_category_limit,
        )
