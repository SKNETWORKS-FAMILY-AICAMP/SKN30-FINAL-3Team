"""F3 판정에 필요한 장부 조회와 실행 결과 저장.

모든 조회에 `brokerage_id` 를 건다. 후보 추출은 여기서 SQL 로 1차 필터(가격 게이트)를 걸고
정렬·상한 컷은 `candidates.select_candidates` 가 순수 함수로 처리한다.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select, true
from sqlmodel import Session, col

from domain.negotiation.candidates import CandidateRow
from domain.negotiation.models import (
    AgentRun,
    MatchCandidateEvaluation,
    MatchEvaluation,
    NegotiationPositionAnalysis,
    NegotiationPositionEvidence,
)
from domain.property_ledger.models import (
    ClientInteraction,
    Party,
    PropertyListing,
    PropertyRequirement,
    PropertyUnit,
    PropertyUnitPartyRelation,
)
from domain.property_ledger.repository import latest_listing_alias

WON_PER_EOK = 100_000_000


def find_unit(session: Session, brokerage_id: int, unit_id: int) -> PropertyUnit | None:
    statement = select(PropertyUnit).where(
        col(PropertyUnit.brokerage_id) == brokerage_id,
        col(PropertyUnit.id) == unit_id,
        col(PropertyUnit.is_deleted).is_(False),
    )
    return session.execute(statement).scalars().first()


def find_requirement(
    session: Session, brokerage_id: int, requirement_id: int
) -> tuple[PropertyRequirement, Party] | None:
    statement = (
        select(PropertyRequirement, Party)
        .join(
            Party,
            (col(Party.brokerage_id) == PropertyRequirement.brokerage_id)
            & (col(Party.id) == PropertyRequirement.party_id),
        )
        .where(
            col(PropertyRequirement.brokerage_id) == brokerage_id,
            col(PropertyRequirement.id) == requirement_id,
            col(PropertyRequirement.is_deleted).is_(False),
        )
    )
    return session.execute(statement).first()  # pyright: ignore[reportReturnType]


def latest_listing_for_unit(
    session: Session, brokerage_id: int, unit_id: int
) -> PropertyListing | None:
    statement = (
        select(PropertyListing)
        .where(
            col(PropertyListing.brokerage_id) == brokerage_id,
            col(PropertyListing.unit_id) == unit_id,
            col(PropertyListing.is_deleted).is_(False),
        )
        .order_by(col(PropertyListing.received_at).desc(), col(PropertyListing.id).desc())
        .limit(1)
    )
    return session.execute(statement).scalars().first()


def unit_relations(
    session: Session, brokerage_id: int, unit_id: int
) -> list[PropertyUnitPartyRelation]:
    statement = select(PropertyUnitPartyRelation).where(
        col(PropertyUnitPartyRelation.brokerage_id) == brokerage_id,
        col(PropertyUnitPartyRelation.unit_id) == unit_id,
        col(PropertyUnitPartyRelation.valid_to).is_(None),
    )
    return list(session.execute(statement).scalars().all())


def unit_interactions(session: Session, brokerage_id: int, unit_id: int) -> list[ClientInteraction]:
    statement = (
        select(ClientInteraction)
        .where(
            col(ClientInteraction.brokerage_id) == brokerage_id,
            col(ClientInteraction.unit_id) == unit_id,
            col(ClientInteraction.is_voided).is_(False),
        )
        .order_by(col(ClientInteraction.interaction_at).desc(), col(ClientInteraction.id).desc())
    )
    return list(session.execute(statement).scalars().all())


def requirement_interactions(
    session: Session, brokerage_id: int, requirement_id: int
) -> list[ClientInteraction]:
    statement = (
        select(ClientInteraction)
        .where(
            col(ClientInteraction.brokerage_id) == brokerage_id,
            col(ClientInteraction.requirement_id) == requirement_id,
            col(ClientInteraction.is_voided).is_(False),
        )
        .order_by(col(ClientInteraction.interaction_at).desc(), col(ClientInteraction.id).desc())
    )
    return list(session.execute(statement).scalars().all())


def candidate_rows(
    session: Session,
    brokerage_id: int,
    *,
    deal_type: str,
) -> list[CandidateRow]:
    """후보가 될 수 있는 매물을 전부 가져온다. 매물 건이 없는 세대는 후보가 아니다.

    가격 게이트를 SQL 에 두지 않는다 — 여기서 걸러 버리면 무엇이 왜 빠졌는지 응답에
    남길 수 없다. 제외 사유를 보이는 쪽이 이 단계의 요구사항이라 컷은 코드가 한다.
    장부가 커지면 여기에 넉넉한 상한을 다시 넣고 컷은 그대로 코드에 둔다.

    거래 유형은 앵커와 맞는 축(매매=매매가 · 임대=전세보증금)만 본다. 유형 자체의
    최종 판정은 대리 카드의 `deal_type_now` 로 하드 게이트 G1 에서 다시 걸린다.
    """
    listing = latest_listing_alias()
    price = col(listing.sale_price) if deal_type == "매매" else col(listing.jeonse_deposit_amount)
    available = (
        col(listing.is_sale_available) if deal_type == "매매" else col(listing.is_jeonse_available)
    )
    statement = (
        select(
            col(PropertyUnit.id),
            col(PropertyUnit.building_number),
            col(PropertyUnit.unit_number),
            col(PropertyUnit.pyeong),
            price,
        )
        # latest_listing_alias 는 PropertyUnit 에 상관된 LATERAL 이라 ON 절이 필요 없다.
        .join(listing, true())
        .where(
            col(PropertyUnit.brokerage_id) == brokerage_id,
            col(PropertyUnit.is_deleted).is_(False),
            available.is_(True),
            price.is_not(None),
        )
        .order_by(col(PropertyUnit.id).asc())
    )
    return [
        CandidateRow(
            unit_id=row[0],
            label=f"{row[1]}동 {row[2]}호",
            book_amount=round(row[4] / WON_PER_EOK, 4),
            pyeong=float(row[3]) if row[3] is not None else None,
        )
        for row in session.execute(statement).all()
    ]


def interaction_fingerprint(
    session: Session,
    brokerage_id: int,
    *,
    unit_id: int | None = None,
    requirement_id: int | None = None,
) -> tuple[int, datetime | None]:
    """카드 캐시 키의 재료 — (로그 건수, 최종 로그 시각).

    로그가 하나라도 늘거나 최신 로그가 바뀌면 캐시 키가 달라져 카드가 다시 생성된다
    (수용 기준 13 · F3-PC-11).
    """
    statement = select(
        func.count(col(ClientInteraction.id)), func.max(col(ClientInteraction.interaction_at))
    ).where(
        col(ClientInteraction.brokerage_id) == brokerage_id,
        col(ClientInteraction.is_voided).is_(False),
    )
    if unit_id is not None:
        statement = statement.where(col(ClientInteraction.unit_id) == unit_id)
    else:
        statement = statement.where(col(ClientInteraction.requirement_id) == requirement_id)
    count, latest = session.execute(statement).one()
    return int(count), latest


def find_valid_position_analysis(
    session: Session, brokerage_id: int, cache_key: str
) -> NegotiationPositionAnalysis | None:
    """캐시 히트 판정 (F3-PC-11 · 수용 기준 13). 무효화된 카드는 히트가 아니다."""
    statement = (
        select(NegotiationPositionAnalysis)
        .where(
            col(NegotiationPositionAnalysis.brokerage_id) == brokerage_id,
            col(NegotiationPositionAnalysis.cache_key) == cache_key,
            col(NegotiationPositionAnalysis.invalidated_at).is_(None),
        )
        .order_by(col(NegotiationPositionAnalysis.generated_at).desc())
        .limit(1)
    )
    return session.execute(statement).scalars().first()


def add_agent_run(session: Session, run: AgentRun) -> AgentRun:
    session.add(run)
    session.flush()
    return run


def add_position_analysis(
    session: Session,
    analysis: NegotiationPositionAnalysis,
    evidence: list[NegotiationPositionEvidence],
) -> NegotiationPositionAnalysis:
    session.add(analysis)
    session.flush()
    for row in evidence:
        row.position_analysis_id = analysis.id or 0
        session.add(row)
    session.flush()
    return analysis


def add_match_evaluation(
    session: Session,
    evaluation: MatchEvaluation,
    candidates: list[MatchCandidateEvaluation],
) -> MatchEvaluation:
    session.add(evaluation)
    session.flush()
    for row in candidates:
        row.match_evaluation_id = evaluation.id or 0
        session.add(row)
    session.flush()
    return evaluation
