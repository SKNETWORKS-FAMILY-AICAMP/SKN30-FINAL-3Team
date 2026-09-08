"""활성 장부의 포지션 카드를 미리 채우는 일회성 작업.

## 왜 필요한가

매물·손님을 API 로 저장하면 `triggers` 가 `LEDGER_SAVE` 실행을 접수하고, Worker 가 앵커 카드를
만든 뒤 `ANCHOR_READY` 로 주차한다. 그래서 **평소에는 카드가 저절로 채워진다.**

문제는 그 경로를 거치지 않고 들어온 장부다. seed SQL 로 적재한 데이터가 그렇다. 카드가 없으면
교차 판정 때 앵커 1장 + 후보 N장을 그 자리에서 만들어야 하고, 그게 실행 시간의 8할이다.

포지션 카드는 **쌍이 아니라 앵커당 하나**다. 캐시 키에 "누가 요청했는지"가 없어 같은 카드가
앵커로도 후보로도 재사용된다. 그래서 활성 앵커 수만큼(O(N)) 한 번 채워 두면 이후 판정은
후보 조회 SQL 과 판정 호출 1회로 끝난다.

## 이 명령이 하는 일

접수만 한다. **모델을 부르지 않는다.** 실제 카드 생성은 Worker 가 한다. 활성 실행이 이미 있는
앵커는 `queue_cross_judgment_run` 이 그것을 돌려주므로 몇 번을 돌려도 중복 접수되지 않는다.

Worker 는 실행을 하나씩 선점한다. 앵커가 많아 오래 걸리면 Worker 프로세스를 여러 개 띄운다.
lease owner 가 프로세스마다 달라 서로 다른 실행을 가져간다.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from sqlmodel import Session, col, func, select

from domain.agent_execution import repository, service
from domain.agent_execution.candidates import (
    ACTIVE_LISTING_STATUSES,
    ACTIVE_REQUIREMENT_STATUSES,
)
from domain.agent_execution.models import LEDGER_SAVE_TRIGGER_TYPE, AgentRun, AnchorType
from domain.property_ledger.models import PropertyListing, PropertyRequirement

logger = structlog.get_logger()


@dataclass(frozen=True)
class BackfillResult:
    """접수 결과. 카드가 몇 장 생겼는지가 아니라 **무엇을 접수했는지**를 담는다."""

    brokerage_id: int
    listings: int
    requirements: int
    queued: int
    reused: int
    failed: int
    dry_run: bool


def _anchor_ids(session: Session, brokerage_id: int) -> list[tuple[AnchorType, int]]:
    """후보 선별이 활성으로 보는 것과 **같은 범위**를 쓴다.

    범위가 갈리면 백필이 판정에 쓰이지 않을 카드를 만들거나, 쓰일 카드를 빠뜨린다.
    """
    listings = session.exec(
        select(col(PropertyListing.id)).where(
            col(PropertyListing.brokerage_id) == brokerage_id,
            col(PropertyListing.is_deleted).is_(False),
            col(PropertyListing.status).in_(sorted(ACTIVE_LISTING_STATUSES)),
        )
    ).all()
    requirements = session.exec(
        select(col(PropertyRequirement.id)).where(
            col(PropertyRequirement.brokerage_id) == brokerage_id,
            col(PropertyRequirement.is_deleted).is_(False),
            col(PropertyRequirement.status).in_(sorted(ACTIVE_REQUIREMENT_STATUSES)),
        )
    ).all()
    return [
        *((AnchorType.LISTING, anchor_id) for anchor_id in listings if anchor_id),
        *((AnchorType.REQUIREMENT, anchor_id) for anchor_id in requirements if anchor_id),
    ]


def backfill_position_cards(
    session: Session,
    *,
    brokerage_id: int,
    requested_by: int,
    limit: int | None = None,
    dry_run: bool = False,
) -> BackfillResult:
    """활성 앵커마다 `LEDGER_SAVE` 실행을 접수한다.

    `limit` 은 한 번에 접수할 앵커 수를 제한한다. GPU 를 오래 점유하고 싶지 않을 때 나눠서
    돌리기 위한 것이며, 멱등하므로 같은 명령을 반복하면 남은 것부터 채워진다.
    """
    anchors = _anchor_ids(session, brokerage_id)
    listings = sum(1 for kind, _ in anchors if kind is AnchorType.LISTING)
    requirements = len(anchors) - listings
    if limit is not None:
        anchors = anchors[:limit]

    if dry_run:
        return BackfillResult(
            brokerage_id=brokerage_id,
            listings=listings,
            requirements=requirements,
            queued=len(anchors),
            reused=0,
            failed=0,
            dry_run=True,
        )

    # 새로 만든 실행과 재사용한 실행을 id 로 가른다. 접수 전 최대 id 보다 큰 것이 새 실행이다.
    baseline = session.exec(select(func.max(col(AgentRun.id)))).one() or 0

    queued = reused = failed = 0
    for anchor_type, anchor_id in anchors:
        try:
            run = service.queue_cross_judgment_run(
                session,
                brokerage_id,
                requested_by,
                anchor_type,
                anchor_id,
                trigger_type=LEDGER_SAVE_TRIGGER_TYPE,
            )
        except Exception as error:  # noqa: BLE001 - 앵커 하나의 실패로 백필 전체를 멈추지 않는다
            session.rollback()
            failed += 1
            logger.warning(
                "f3_backfill_intake_failed",
                anchor_type=anchor_type.value,
                anchor_id=anchor_id,
                error_type=type(error).__name__,
            )
            continue
        if (run.id or 0) > baseline:
            queued += 1
        else:
            reused += 1

    logger.info(
        "f3_backfill_completed",
        brokerage_id=brokerage_id,
        queued=queued,
        reused=reused,
        failed=failed,
    )
    return BackfillResult(
        brokerage_id=brokerage_id,
        listings=listings,
        requirements=requirements,
        queued=queued,
        reused=reused,
        failed=failed,
        dry_run=False,
    )


def position_card_coverage(session: Session, brokerage_id: int) -> dict[str, int]:
    """활성 앵커 중 유효한 카드를 가진 비율. 백필 전후를 눈으로 확인할 때 쓴다.

    cache key 까지 대조하지는 않는다. 여기서 세는 것은 "무효화되지 않은 카드가 있는가"이며,
    프롬프트 버전이 바뀌어 실제로는 다시 만들어야 하는 카드도 포함된다.
    """
    anchors = _anchor_ids(session, brokerage_id)
    listing_ids = {anchor_id for kind, anchor_id in anchors if kind is AnchorType.LISTING}
    requirement_ids = {anchor_id for kind, anchor_id in anchors if kind is AnchorType.REQUIREMENT}
    covered_listings, covered_requirements = repository.count_covered_anchors(
        session, brokerage_id, listing_ids, requirement_ids
    )
    return {
        "active_listings": len(listing_ids),
        "covered_listings": covered_listings,
        "active_requirements": len(requirement_ids),
        "covered_requirements": covered_requirements,
    }
