"""Time Keeper 일정·할 일 조회의 읽기 모델.

새 테이블을 만들지 않는다. F1 장부가 이미 소유한 날짜 컬럼에서 "언제까지 무엇을 해야 하는가"를
뽑아 한 목록으로 합쳐 읽기만 한다. 날짜 계산은 SQL과 순수 함수가 하고 이 경로에는 모델 호출이
없다. F3 17장이 "만기 보드 → F1", "날짜 계산 → 코드. LLM은 날짜 산수를 틀린다"로 이미 정리한
판단을 따른다.

아직 담지 못하는 항목은 `AgendaCategory` 주석에 근거와 함께 남긴다. 없는 데이터를 있는 것처럼
보여주지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from enum import StrEnum

from core.errors import ValidationError
from domain.property_ledger.models import Party, PartyContact

# 중개사무소의 업무 시간대. 대한민국은 서머타임을 쓰지 않으므로 고정 오프셋으로 충분하고,
# zoneinfo를 쓰면 IANA 데이터가 없는 개발 환경에서 조회가 통째로 실패한다.
KST = timezone(timedelta(hours=9))

# PostgreSQL 쪽 날짜 변환에 쓰는 같은 시간대. 서버는 IANA 이름을 내장하므로 여기서는 이름을 쓴다.
BUSINESS_TIMEZONE = "Asia/Seoul"

# 앞으로 며칠까지 볼지의 기본값. F1-AL-01의 "만기 N개월 전, 기본 3개월"을 일수로 옮겼다.
DEFAULT_WITHIN_DAYS = 90
MAX_WITHIN_DAYS = 730

# 이미 지난 일정을 며칠까지 함께 볼지의 기본값. 어제 지난 만기가 목록에서 사라지면 놓친 건을
# 다시 만날 자리가 없다. 이 목록의 목적은 "할 일"을 찾는 것이지 달력을 그리는 것이 아니다.
DEFAULT_OVERDUE_DAYS = 7
MAX_OVERDUE_DAYS = 365

# 마지막 접촉 후 이 일수가 지나면 재연락 대상으로 본다 (F1-AL-03).
# 매물 접수 후 이 일수가 지나면 조건이 아직 유효한지 재확인 대상으로 본다.
# 두 값 모두 MVP 조정값이며 승인된 요구사항 수치가 아니다. 사무소별 설정이 생기면 그리로 옮긴다.
DEFAULT_RECONTACT_DAYS = 30
DEFAULT_REVALIDATION_DAYS = 30
MAX_RULE_DAYS = 365

# 한 종류에서 실을 최대 건수.
#
# 브리핑은 종류별로 묶어 보여주므로, 전체를 기한 순으로만 자르면 임박한 한 종류가 지면을 다
# 먹고 다른 종류는 그날 아예 보이지 않는다. 종류마다 앞에서 몇 건씩 떼어 두면 해당되는 종류는
# 모두 한 번씩 드러나고, 남은 건수는 종류별 총계로 알린다.
DEFAULT_PER_CATEGORY_LIMIT = 3
MAX_PER_CATEGORY_LIMIT = 100


class AgendaCategory(StrEnum):
    """일정 한 건의 종류.

    값은 어휘이지 화면 문구가 아니다. 표시 문자열은 Frontend가 소유하며, 모르는 값을 만나면
    코드를 그대로 보여주고 넘어간다. 아래 목록은 앞으로 늘어난다.

    아직 만들 수 없는 항목과 이유:

    - 계약 체결일, 계약금·중도금·잔금 지급일, 신고·서류 제출 기한
      → 계약 테이블이 없다. F1-CT-01~03이 미구현이라 계약 건 자체가 저장되지 않는다.
        거래신고 기한은 계약일에서 세는 값이므로 계약일이 생겨야 계산할 수 있다.
    - 임장·매물 방문일
      → 일정 테이블이 없다. F1-SC-01~05가 미구현이다. F3-IF-04의 "승인된 일정 제안만 F1에
        등록한다"도 같은 이유로 아직 쓸 곳이 없다.
    - 명도일
      → `property_listing.handover_condition`은 "만기후" 같은 자유 문구이지 날짜가 아니다.
    """

    #: 세대의 현 임대차 만기 (`property_unit.tenancy_expiry_date`)
    TENANCY_EXPIRY = "TENANCY_EXPIRY"
    #: 손님이 지금 사는 집의 임대차 만기 (`property_requirement.current_tenancy_expiry_date`)
    CLIENT_TENANCY_EXPIRY = "CLIENT_TENANCY_EXPIRY"
    #: 구입 의뢰 자체의 만기 (`property_requirement.request_expiry_date`)
    REQUEST_EXPIRY = "REQUEST_EXPIRY"
    #: 손님의 희망 입주일 (`property_requirement.desired_move_in_date`)
    MOVE_IN = "MOVE_IN"
    #: 세대 재연락 시점. 마지막 접촉 + 재연락 주기
    LISTING_RECONTACT = "LISTING_RECONTACT"
    #: 손님 재연락 시점. 마지막 접촉 + 재연락 주기
    CLIENT_RECONTACT = "CLIENT_RECONTACT"
    #: 매물 조건 재확인 시점. 접수일 + 재확인 주기
    LISTING_REVALIDATION = "LISTING_REVALIDATION"


@dataclass(frozen=True)
class AgendaWindow:
    """조회 구간과 규칙 주기. ``earliest``와 ``latest``는 양끝을 포함한다."""

    as_of: date
    earliest: date
    latest: date
    recontact_days: int
    revalidation_days: int
    per_category_limit: int


@dataclass(frozen=True)
class AgendaRow:
    """union 결과 한 줄. 상세와 인물은 페이지를 자른 뒤에 채운다."""

    category: AgendaCategory
    due_date: date
    unit_id: int | None
    listing_id: int | None
    requirement_id: int | None


@dataclass(frozen=True)
class UnitAgendaDetail:
    """세대에서 온 일정이 화면에 보여줄 장부 값."""

    unit_id: int
    complex_name: str
    building_number: str | None
    unit_number: str
    tenancy_status: str | None
    assigned_user_id: int | None
    last_contact_at: datetime | None


@dataclass(frozen=True)
class RequirementAgendaDetail:
    """구입장에서 온 일정이 화면에 보여줄 장부 값."""

    requirement_id: int
    party_id: int
    demand_type: str
    status: str
    assigned_user_id: int | None
    last_contact_at: datetime | None


@dataclass(frozen=True)
class AgendaContact:
    """일정 한 건에 연락할 대상 한 명.

    ``role``은 세대 관계 역할(``LANDLORD``·``TENANT``)이며 구입장 손님은 관계 테이블을 거치지
    않으므로 ``None``이다.
    """

    role: str | None
    is_primary: bool
    party: Party
    contacts: tuple[PartyContact, ...]


@dataclass(frozen=True)
class AgendaEntry:
    """일정 목록 한 행. 세대에서 왔으면 구입장 필드가, 반대면 세대 필드가 비어 있다."""

    category: AgendaCategory
    due_date: date
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
    contacts: tuple[AgendaContact, ...]


@dataclass(frozen=True)
class AgendaCategoryCount:
    """창 안에 실제로 존재하는 종류와 그 건수.

    건수가 0인 종류는 아예 나오지 않는다. 화면이 "해당되는 것만" 보여줄 수 있는 근거이며,
    종류별 상한 때문에 잘린 건수를 정직하게 알리는 값이기도 하다.
    """

    category: AgendaCategory
    total: int


@dataclass(frozen=True)
class AgendaPage:
    """조회 결과와 그 결과를 만든 조건.

    화면이 "무엇을 기준으로 며칠 치를 본 목록인지"를 다시 계산하지 않도록 창을 함께 싣는다.
    사용자 브라우저의 자정과 서버의 자정이 어긋나도 같은 기준일을 보게 된다.

    ``total``과 ``categories``는 종류별 상한을 적용하기 **전** 창 전체의 건수다. ``items``는
    상한과 페이지를 적용한 뒤 실제로 실린 행이므로 둘이 다를 수 있다.
    """

    items: tuple[AgendaEntry, ...]
    categories: tuple[AgendaCategoryCount, ...]
    total: int
    limit: int
    offset: int
    as_of: date
    within_days: int
    overdue_days: int
    per_category_limit: int


def today_in_business_timezone(now: datetime | None = None) -> date:
    """중개사무소 기준의 오늘.

    UTC 날짜를 그대로 쓰면 한국 시각 오전 9시 이전에는 하루가 밀려 D-day가 하루씩 틀린다.
    """
    moment = datetime.now(KST) if now is None else now
    return moment.astimezone(KST).date()


def build_window(
    as_of: date,
    within_days: int,
    overdue_days: int,
    *,
    recontact_days: int = DEFAULT_RECONTACT_DAYS,
    revalidation_days: int = DEFAULT_REVALIDATION_DAYS,
    per_category_limit: int = DEFAULT_PER_CATEGORY_LIMIT,
) -> AgendaWindow:
    """조회 구간을 만든다. API 밖에서 호출해도 상한을 넘지 못하게 여기서 다시 검증한다."""
    if not 1 <= within_days <= MAX_WITHIN_DAYS:
        raise ValidationError(f"within_days must be between 1 and {MAX_WITHIN_DAYS}")
    if not 0 <= overdue_days <= MAX_OVERDUE_DAYS:
        raise ValidationError(f"overdue_days must be between 0 and {MAX_OVERDUE_DAYS}")
    if not 1 <= recontact_days <= MAX_RULE_DAYS:
        raise ValidationError(f"recontact_days must be between 1 and {MAX_RULE_DAYS}")
    if not 1 <= revalidation_days <= MAX_RULE_DAYS:
        raise ValidationError(f"revalidation_days must be between 1 and {MAX_RULE_DAYS}")
    if not 1 <= per_category_limit <= MAX_PER_CATEGORY_LIMIT:
        raise ValidationError(f"per_category_limit must be between 1 and {MAX_PER_CATEGORY_LIMIT}")
    return AgendaWindow(
        as_of=as_of,
        earliest=as_of - timedelta(days=overdue_days),
        latest=as_of + timedelta(days=within_days),
        recontact_days=recontact_days,
        revalidation_days=revalidation_days,
        per_category_limit=per_category_limit,
    )


def days_until_due(due: date, as_of: date) -> int:
    """기한까지 남은 일수. 오늘이면 0이고 이미 지났으면 음수다."""
    return (due - as_of).days


def recontact_contact_bounds(window: AgendaWindow) -> tuple[datetime, datetime]:
    """재연락 기한이 창 안에 드는 ``last_contact_at`` 구간. 아래는 닫히고 위는 열린다.

    조건을 컬럼이 아니라 상수 쪽에 둔다. ``날짜(last_contact_at) + 주기 BETWEEN a AND b`` 로 쓰면
    컬럼에 연산이 붙어 인덱스를 타지 못하고 매번 전체를 훑는다. 같은 뜻을 ``last_contact_at`` 자체의
    범위로 옮기면 부분 인덱스를 그대로 쓴다.

    경계는 사무소 시간대의 자정이다. 위쪽을 열어 두는 이유는 마지막 날 하루를 통째로 담기 위해서다.
    """
    shift = timedelta(days=window.recontact_days)
    lower = datetime.combine(window.earliest - shift, time.min, tzinfo=KST)
    upper = datetime.combine(window.latest - shift + timedelta(days=1), time.min, tzinfo=KST)
    return lower, upper


def revalidation_received_bounds(window: AgendaWindow) -> tuple[date, date]:
    """재확인 기한이 창 안에 드는 ``received_at`` 구간. 양끝을 포함한다.

    ``received_at`` 은 DATE 라 시간대 변환 없이 날짜끼리 옮기면 된다.
    """
    shift = timedelta(days=window.revalidation_days)
    return window.earliest - shift, window.latest - shift
