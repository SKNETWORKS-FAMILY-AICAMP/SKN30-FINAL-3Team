from __future__ import annotations

from sqlmodel import Session

from domain.agent_execution.models import AgentRun
from domain.property_ledger import repository as ledger_repository
from domain.property_ledger.models import PropertyListing, PropertyRequirement


def add_agent_run(session: Session, run: AgentRun) -> AgentRun:
    session.add(run)
    session.flush()
    return run


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
