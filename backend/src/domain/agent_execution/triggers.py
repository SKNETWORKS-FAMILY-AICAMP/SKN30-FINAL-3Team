"""F1 저장 성공 뒤 F3 교차 판정을 비차단으로 접수한다.

F1과 F3는 별도 transaction이다. 호출자는 F1 commit이 끝난 뒤 이 모듈을 호출하며,
F3 접수 실패는 이미 성공한 장부 저장이나 HTTP 응답을 바꾸지 않는다. 이 경계에서는
모델을 호출하지 않고 기존 실행 접수 유스케이스로 ``agent_run``만 적재한다.

이 경로로 만든 실행은 앵커 포지션 카드까지만 만들고 ``ANCHOR_READY`` 에서 멈춘다.
후보 조회와 판정은 사용자가 상세에서 요청할 때 같은 실행이 이어서 돈다(F3-CR-01~04).
"""

from __future__ import annotations

from collections.abc import Iterable

import structlog
from sqlmodel import Session

from domain.agent_execution import service
from domain.agent_execution.models import LEDGER_SAVE_TRIGGER_TYPE, AnchorType

logger = structlog.get_logger()


# 매물에서 교차 판정 입력이 되는 필드. 메모와 담당자 같은 운영 필드는 제외한다.
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

# 구입장에서 교차 판정 입력이 되는 필드.
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
        "desired_complex_ids",
    }
)


def touches_judgment_input(changed: Iterable[str], relevant: frozenset[str]) -> bool:
    """F1 서비스가 판정한 실제 변경 필드가 교차 판정 입력을 건드렸는지 확인한다."""
    return bool(set(changed) & relevant)


def queue_after_ledger_save(
    session: Session,
    brokerage_id: int,
    requested_by: int,
    anchor_type: AnchorType,
    anchor_id: int,
) -> int | None:
    """F3 실행을 접수하고 실행 ID를 반환한다. 실패는 안전한 메타데이터만 기록한다."""
    try:
        queued = service.queue_cross_judgment_run(
            session,
            brokerage_id,
            requested_by,
            anchor_type,
            anchor_id,
            trigger_type=LEDGER_SAVE_TRIGGER_TYPE,
        )
    except Exception as error:  # noqa: BLE001 - F1 성공을 F3 장애와 격리하는 경계다.
        session.rollback()
        logger.warning(
            "f3_auto_intake_failed",
            anchor_type=anchor_type.value,
            anchor_id=anchor_id,
            error_type=type(error).__name__,
        )
        return None

    logger.info(
        "f3_auto_intake_queued",
        run_id=queued.id,
        anchor_type=anchor_type.value,
        anchor_id=anchor_id,
    )
    return queued.id


def after_listing_saved(
    session: Session,
    brokerage_id: int,
    requested_by: int,
    listing_id: int,
    changed: Iterable[str] | None = None,
) -> int | None:
    """매물 신규 등록 또는 실제 판정 입력 변경 뒤 실행을 접수한다 (F3-CR-02)."""
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
    """구입장 신규 등록 또는 실제 조건 변경 뒤 실행을 접수한다 (F3-CR-01)."""
    if changed is not None and not touches_judgment_input(changed, REQUIREMENT_TRIGGER_FIELDS):
        return None
    return queue_after_ledger_save(
        session, brokerage_id, requested_by, AnchorType.REQUIREMENT, requirement_id
    )
