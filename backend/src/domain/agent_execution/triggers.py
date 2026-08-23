"""F1 저장 성공 후의 F3 교차 판정 자동 접수 (F3-CR-01, F3-CR-02).

가격 변경이 저장 이벤트라는 점이 핵심이다. 112동 401호를 27.5억에서 26.5억으로 내리는
순간, 어제까지 예산이 모자라 빠졌던 손님들이 후보로 올라온다. 별도 배치나 브리핑이 필요
없다.

## 지키는 것

- **F1 저장 transaction 과 분리한다.** F1 이 commit 을 끝낸 뒤에 부른다.
- **F3 접수 실패가 성공한 F1 저장을 되돌리지 않는다** (F3-NF-07, F3-CM-06). 어떤 예외도
  밖으로 나가지 않고 구조화 로그로만 남는다.
- **요청 처리 중 모델을 부르지 않는다.** 하는 일은 `agent_run` 적재까지다.
- **기존 재사용 로직을 그대로 쓴다.** 같은 앵커·입력 버전의 실행이 있으면 새로 만들지 않는다.
- 실패 로그에 상담 원문과 개인정보를 남기지 않는다. 남기는 것은 앵커 종류·ID 와 예외
  타입 이름뿐이다.

## 언제 부르지 않는가

가격이나 조건이 실제로 바뀌지 않은 수정에서는 부르지 않는다. 담당자 메모만 고친 저장이
판정을 다시 돌릴 이유는 없다. 어떤 필드가 판정 입력인지는 아래 두 집합이 정한다.

행이 실제로 바뀌면 `row_version` 이 오르고, 그 값이 재사용 키에 들어간다. 그래서 값이 그대로인
저장은 여기까지 와도 새 실행을 만들지 않고 기존 실행을 돌려준다. 필드 집합은 그보다 앞에서
불필요한 조회 자체를 줄이는 층이다.
"""

from __future__ import annotations

from collections.abc import Iterable

import structlog
from sqlmodel import Session

from domain.agent_execution import service
from domain.agent_execution.models import AnchorType

logger = structlog.get_logger()

# 자동 접수 실행의 trigger. 사용자가 화면에서 직접 누른 USER_REQUEST 와 구분한다.
LEDGER_SAVE_TRIGGER_TYPE = "LEDGER_SAVE"

# 매물에서 판정 입력이 되는 필드. 이 중 하나라도 바뀌면 다시 판정할 이유가 있다.
LISTING_TRIGGER_FIELDS = frozenset(
    {
        "is_sale_available",
        "sale_price",
        "is_jeonse_available",
        "jeonse_deposit_amount",
        "is_monthly_rent_available",
        "monthly_rent_deposit_amount",
        "monthly_rent_amount",
        "price_raw_text",
        "handover_condition",
        "status",
        "client_party_id",
    }
)

# 구입장에서 판정 입력이 되는 필드.
REQUIREMENT_TRIGGER_FIELDS = frozenset(
    {
        "demand_type",
        "status",
        "classification",
        "workflow_stage",
        "min_budget_amount",
        "max_budget_amount",
        "budget_raw_text",
        "desired_pyeongs",
        "min_area_sqm",
        "max_area_sqm",
        "area_requirement_raw_text",
        "desired_move_in_date",
        "move_in_date_raw_text",
        "request_expiry_date",
        "current_tenancy_expiry_date",
        "co_broker_party_id",
        "complex_ids",
    }
)


def touches_judgment_input(changed: Iterable[str], relevant: frozenset[str]) -> bool:
    """이번 저장이 판정 입력을 건드렸는가.

    `row_version` 은 항상 실려 오므로 판정 대상에서 뺀다. 그것만 보고 판단하면 모든 수정이
    판정 입력을 바꾼 것이 된다.
    """
    return bool({field for field in changed if field != "row_version"} & relevant)


def queue_after_ledger_save(
    session: Session,
    brokerage_id: int,
    requested_by: int,
    anchor_type: AnchorType,
    anchor_id: int,
) -> int | None:
    """F1 저장 성공 후 F3 실행을 접수한다. 실패해도 예외를 올리지 않는다.

    돌려주는 값은 실행 ID 이거나, 접수하지 못했으면 `None` 이다. 호출자는 이 값을 응답에
    싣지 않아도 된다. F1 응답 계약은 이 트리거 때문에 바뀌지 않는다.
    """
    try:
        queued = service.queue_cross_judgment_run(
            session,
            brokerage_id,
            requested_by,
            anchor_type,
            anchor_id,
            trigger_type=LEDGER_SAVE_TRIGGER_TYPE,
        )
    except BaseException as error:  # noqa: BLE001 - 성공한 F1 저장을 되돌리지 않는 것이 목적이다
        session.rollback()
        # 상담 원문과 개인정보를 남기지 않는다. 앵커와 예외 타입 이름까지만 남긴다.
        logger.warning(
            "f3_auto_intake_failed",
            anchor_type=anchor_type.value,
            anchor_id=anchor_id,
            error_type=type(error).__name__,
        )
        return None

    logger.info(
        "f3_auto_intake",
        run_id=queued.run.id,
        anchor_type=anchor_type.value,
        anchor_id=anchor_id,
        reused=queued.reused,
    )
    return queued.run.id


def after_listing_saved(
    session: Session,
    brokerage_id: int,
    requested_by: int,
    listing_id: int,
    changed: Iterable[str] | None = None,
) -> int | None:
    """매물 신규 등록·가격 변경 저장 후 (F3-CR-02).

    `changed` 가 없으면 신규 등록이라 항상 접수한다.
    """
    if changed is not None and not touches_judgment_input(changed, LISTING_TRIGGER_FIELDS):
        return None
    return queue_after_ledger_save(
        session, brokerage_id, requested_by, AnchorType.LISTING, listing_id
    )


def after_requirement_saved(
    session: Session,
    brokerage_id: int,
    requested_by: int,
    requirement_id: int,
    changed: Iterable[str] | None = None,
) -> int | None:
    """구입장 신규 등록·조건 수정 저장 후 (F3-CR-01)."""
    if changed is not None and not touches_judgment_input(changed, REQUIREMENT_TRIGGER_FIELDS):
        return None
    return queue_after_ledger_save(
        session, brokerage_id, requested_by, AnchorType.REQUIREMENT, requirement_id
    )
