from __future__ import annotations

from sqlmodel import Session, col, select

from domain.agent_execution.models import CROSS_JUDGMENT_RUN_TYPE, AgentRun
from domain.property_ledger import repository as ledger_repository
from domain.property_ledger.models import PropertyListing, PropertyRequirement


def add_agent_run(session: Session, run: AgentRun) -> AgentRun:
    session.add(run)
    session.flush()
    return run


def find_root_cross_judgment_run(
    session: Session, brokerage_id: int, run_id: int
) -> AgentRun | None:
    """사용자가 접수한 루트 교차 판정만 돌려준다. 내부 하위 실행은 조회 대상이 아니다."""
    statement = select(AgentRun).where(
        col(AgentRun.brokerage_id) == brokerage_id,
        col(AgentRun.id) == run_id,
        col(AgentRun.run_type) == CROSS_JUDGMENT_RUN_TYPE,
        col(AgentRun.parent_run_id).is_(None),
    )
    return session.execute(statement).scalars().first()


def find_listing_anchor(
    session: Session, brokerage_id: int, listing_id: int
) -> PropertyListing | None:
    """매물 앵커. 조회 범위는 F1 매물장과 같아야 하므로 장부 repository를 그대로 쓴다."""
    return ledger_repository.find_property_listing(session, brokerage_id, listing_id)


def find_requirement_anchor(
    session: Session, brokerage_id: int, requirement_id: int
) -> PropertyRequirement | None:
    """손님 앵커. 장부 조회는 인물을 함께 돌려주지만 실행 대상은 구입장 행이다."""
    found = ledger_repository.find_property_requirement(session, brokerage_id, requirement_id)
    return found[0] if found is not None else None
