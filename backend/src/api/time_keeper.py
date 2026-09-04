from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from api.schemas.property_ledger import MAX_PAGE_SIZE
from api.schemas.time_keeper import AgendaListResponse
from domain.authentication.dependencies import get_current_user
from domain.authentication.models import CurrentUser
from domain.session import get_db_session
from domain.time_keeper import service
from domain.time_keeper.models import (
    DEFAULT_OVERDUE_DAYS,
    DEFAULT_PER_CATEGORY_LIMIT,
    DEFAULT_RECONTACT_DAYS,
    DEFAULT_REVALIDATION_DAYS,
    DEFAULT_WITHIN_DAYS,
    MAX_OVERDUE_DAYS,
    MAX_PER_CATEGORY_LIMIT,
    MAX_RULE_DAYS,
    MAX_WITHIN_DAYS,
)

router = APIRouter(prefix="/time-keeper", tags=["time-keeper"])

DEFAULT_PAGE_SIZE = 50


@router.get("/agenda", response_model=AgendaListResponse)
def list_agenda(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db_session),
    within_days: int = Query(default=DEFAULT_WITHIN_DAYS, ge=1, le=MAX_WITHIN_DAYS),
    overdue_days: int = Query(default=DEFAULT_OVERDUE_DAYS, ge=0, le=MAX_OVERDUE_DAYS),
    recontact_days: int = Query(default=DEFAULT_RECONTACT_DAYS, ge=1, le=MAX_RULE_DAYS),
    revalidation_days: int = Query(default=DEFAULT_REVALIDATION_DAYS, ge=1, le=MAX_RULE_DAYS),
    per_category_limit: int = Query(
        default=DEFAULT_PER_CATEGORY_LIMIT, ge=1, le=MAX_PER_CATEGORY_LIMIT
    ),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
) -> AgendaListResponse:
    """기한이 다가온 일정과 할 일을 이른 순으로 조회한다.

    장부에 날짜가 적혀 있는 일정(임대차 만기, 의뢰 만기, 희망 입주일)과 주기 규칙으로 만드는
    할 일(재연락, 매물 조건 재확인)을 한 목록으로 합친다. 읽기 전용이며 장부를 바꾸지 않고
    모델도 호출하지 않는다.

    해당되는 것이 없는 종류는 응답에 나오지 않는다. 종류마다 ``per_category_limit`` 건씩 떼어
    실으므로 임박한 한 종류가 나머지를 밀어내지 않으며, 잘린 건수는 ``categories``의 총계와
    실린 건수의 차이로 드러난다.
    """
    page = service.load_agenda(
        db,
        user.brokerage_id,
        limit=limit,
        offset=offset,
        within_days=within_days,
        overdue_days=overdue_days,
        recontact_days=recontact_days,
        revalidation_days=revalidation_days,
        per_category_limit=per_category_limit,
    )
    return AgendaListResponse.from_domain(page)
