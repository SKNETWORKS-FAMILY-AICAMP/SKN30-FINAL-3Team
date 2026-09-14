from __future__ import annotations

from collections.abc import Sequence
from typing import Any, NamedTuple

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session, col, select

from domain.agent_execution.models import (
    NegotiationPositionAnalysis,
    NegotiationPositionEvidence,
    NegotiationPositionPrice,
)

from .inputs import InteractionSummary


def _active_position_card_conditions(
    brokerage_id: int,
    *,
    cache_key: str,
    negotiation_side: str,
    listing_id: int | None,
    requirement_id: int | None,
    data_version: int,
    interactions: InteractionSummary,
) -> list[Any]:
    """일반 cache lookup과 저장 단계 잠금 조회가 공유하는 활성 카드 조건."""
    return [
        col(NegotiationPositionAnalysis.brokerage_id) == brokerage_id,
        col(NegotiationPositionAnalysis.cache_key) == cache_key,
        col(NegotiationPositionAnalysis.negotiation_side) == negotiation_side,
        col(NegotiationPositionAnalysis.listing_id).is_not_distinct_from(listing_id),
        col(NegotiationPositionAnalysis.requirement_id).is_not_distinct_from(requirement_id),
        col(NegotiationPositionAnalysis.data_version) == data_version,
        col(NegotiationPositionAnalysis.source_interaction_count) == interactions.interaction_count,
        col(NegotiationPositionAnalysis.last_interaction_at).is_not_distinct_from(
            interactions.last_interaction_at
        ),
        col(NegotiationPositionAnalysis.invalidated_at).is_(None),
    ]


def find_active_position_card(
    session: Session,
    brokerage_id: int,
    *,
    cache_key: str,
    negotiation_side: str,
    listing_id: int | None,
    requirement_id: int | None,
    data_version: int,
    interactions: InteractionSummary,
) -> NegotiationPositionAnalysis | None:
    """재사용 가능한 카드만 돌려준다. 준비 단계라 행 잠금을 잡지 않는다.

    cache_key 만 믿지 않고 저장된 source 값을 다시 대조한다. 키 계산식이 바뀌거나 예전
    schema 로 만든 행이 남아 있어도 낡은 카드를 재사용하지 않는다.
    """
    statement = select(NegotiationPositionAnalysis).where(
        *_active_position_card_conditions(
            brokerage_id,
            cache_key=cache_key,
            negotiation_side=negotiation_side,
            listing_id=listing_id,
            requirement_id=requirement_id,
            data_version=data_version,
            interactions=interactions,
        )
    )
    return session.execute(statement).scalars().first()


def lock_active_position_card_for_store(
    session: Session,
    brokerage_id: int,
    *,
    cache_key: str,
    negotiation_side: str,
    listing_id: int | None,
    requirement_id: int | None,
    data_version: int,
    interactions: InteractionSummary,
) -> NegotiationPositionAnalysis | None:
    """저장할 cache hit 카드를 잠그고 transaction 끝까지 활성 상태를 고정한다.

    단순 재조회 뒤에 다른 transaction이 `invalidated_at`을 갱신하면 무효 카드 ID로 실행을
    확정할 수 있다. 저장 단계에서만 행 잠금을 잡아 그 갱신과 `ANCHOR_READY` 전이를
    직렬화한다. 모델을 호출하는 준비 단계에는 이 함수를 쓰지 않는다.
    """
    statement = (
        select(NegotiationPositionAnalysis)
        .where(
            *_active_position_card_conditions(
                brokerage_id,
                cache_key=cache_key,
                negotiation_side=negotiation_side,
                listing_id=listing_id,
                requirement_id=requirement_id,
                data_version=data_version,
                interactions=interactions,
            )
        )
        .with_for_update()
    )
    return session.execute(statement).scalars().first()


def lock_card_that_won_the_cache_key(
    session: Session, brokerage_id: int, cache_key: str
) -> NegotiationPositionAnalysis | None:
    """저장 경합에서 이긴 활성 카드를 잠그고 돌려준다.

    `ON CONFLICT DO NOTHING` 으로 밀린 쪽이 **이미 같은 키를 넣은 상대 카드**를 찾는 용도다.
    일반 cache lookup 에는 쓰지 않는다. 그쪽은 `find_active_position_card` 가 대상·버전·
    상담 집합까지 함께 대조한다. 이 행도 현재 실행이 확정될 때까지 무효화되면 안 되므로
    transaction 끝까지 잠근다.
    """
    statement = (
        select(NegotiationPositionAnalysis)
        .where(
            col(NegotiationPositionAnalysis.brokerage_id) == brokerage_id,
            col(NegotiationPositionAnalysis.cache_key) == cache_key,
            col(NegotiationPositionAnalysis.invalidated_at).is_(None),
        )
        .with_for_update()
    )
    return session.execute(statement).scalars().first()


def insert_position_card(
    session: Session, card: NegotiationPositionAnalysis
) -> NegotiationPositionAnalysis | None:
    """카드를 넣는다. 다른 실행이 같은 키를 먼저 넣었으면 None 을 돌려준다.

    partial unique index(`uq_position_analysis_active_cache_key`)와 같은 조건으로
    `ON CONFLICT DO NOTHING` 한다. 경합을 예외로 터뜨리면 정상 상황이 실패가 된다.
    """
    values = card.model_dump(exclude_none=True, exclude={"id"})
    statement = (
        pg_insert(NegotiationPositionAnalysis)
        .values(**values)
        .on_conflict_do_nothing(
            index_elements=["brokerage_id", "cache_key"],
            index_where=text("invalidated_at IS NULL"),
        )
        .returning(col(NegotiationPositionAnalysis.id))
    )
    inserted = session.execute(statement).scalars().first()
    if inserted is None:
        return None
    card.id = inserted
    return card


def insert_position_prices(session: Session, prices: Sequence[NegotiationPositionPrice]) -> None:
    if prices:
        session.add_all(list(prices))
        session.flush()


def insert_position_evidence(
    session: Session, evidence: Sequence[NegotiationPositionEvidence]
) -> None:
    if evidence:
        session.add_all(list(evidence))
        session.flush()


class CandidatePriceRow(NamedTuple):
    """카드에 실린 거래 유형별 금액. `display_order` 순서를 그대로 유지한다.

    월세는 보증금과 월 차임이 **별도 축**이라 네 값을 모두 들고 온다. 하나로 접으면 어느
    금액을 비교했는지 알 수 없게 된다.
    """

    price_kind: str
    stated_amount: int | None
    estimated_amount: int | None
    stated_monthly_amount: int | None
    estimated_monthly_amount: int | None


def list_position_card_prices(
    session: Session, brokerage_id: int, position_analysis_id: int
) -> list[CandidatePriceRow]:
    """카드의 금액을 원래 순서로 읽는다. 첫 행이 후보 조회의 가격 축이 된다."""
    statement = (
        select(NegotiationPositionPrice)
        .where(
            col(NegotiationPositionPrice.brokerage_id) == brokerage_id,
            col(NegotiationPositionPrice.position_analysis_id) == position_analysis_id,
        )
        .order_by(
            col(NegotiationPositionPrice.display_order).asc(),
            col(NegotiationPositionPrice.price_kind).asc(),
        )
    )
    return [
        CandidatePriceRow(
            price_kind=row.price_kind,
            stated_amount=row.stated_amount,
            estimated_amount=row.estimated_amount,
            stated_monthly_amount=row.stated_monthly_amount,
            estimated_monthly_amount=row.estimated_monthly_amount,
        )
        for row in session.execute(statement).scalars().all()
    ]


def find_position_card_for_target(
    session: Session,
    brokerage_id: int,
    *,
    position_analysis_id: int,
    negotiation_side: str,
    listing_id: int | None,
    requirement_id: int | None,
) -> NegotiationPositionAnalysis | None:
    """실행이 기록한 카드 ID 를 다시 확인한다. 사무소·측면·대상·활성 여부를 함께 본다."""
    statement = select(NegotiationPositionAnalysis).where(
        col(NegotiationPositionAnalysis.brokerage_id) == brokerage_id,
        col(NegotiationPositionAnalysis.id) == position_analysis_id,
        col(NegotiationPositionAnalysis.negotiation_side) == negotiation_side,
        col(NegotiationPositionAnalysis.listing_id).is_not_distinct_from(listing_id),
        col(NegotiationPositionAnalysis.requirement_id).is_not_distinct_from(requirement_id),
        col(NegotiationPositionAnalysis.invalidated_at).is_(None),
    )
    return session.execute(statement).scalars().first()


class CardEvidenceRow(NamedTuple):
    """카드가 이미 저장해 둔 근거 인용과 그 offset.

    중개 판정의 인용은 새 offset 을 계산하지 않고 이 값을 그대로 옮긴다. 판정 단계에는
    상담 원문이 없으므로 여기 없는 인용은 카드에 근거가 없는 인용이다.
    """

    interaction_id: int
    quote_text: str
    quote_start_offset: int | None
    quote_end_offset: int | None


def list_card_quote_evidence(
    session: Session, brokerage_id: int, position_analysis_id: int
) -> list[CardEvidenceRow]:
    """카드의 인용 근거만 돌려준다. 추정 근거는 인용 대조에 쓰이지 않는다."""
    statement = select(
        col(NegotiationPositionEvidence.interaction_id),
        col(NegotiationPositionEvidence.quote_text),
        col(NegotiationPositionEvidence.quote_start_offset),
        col(NegotiationPositionEvidence.quote_end_offset),
    ).where(
        col(NegotiationPositionEvidence.brokerage_id) == brokerage_id,
        col(NegotiationPositionEvidence.position_analysis_id) == position_analysis_id,
        col(NegotiationPositionEvidence.interaction_id).is_not(None),
        col(NegotiationPositionEvidence.quote_text).is_not(None),
    )
    return [CardEvidenceRow(*row) for row in session.execute(statement).all()]


def list_position_cards(
    session: Session, brokerage_id: int, position_analysis_ids: Sequence[int]
) -> list[NegotiationPositionAnalysis]:
    """활성 카드 여러 건을 한 번에 읽는다. 무효화된 카드는 나오지 않는다."""
    if not position_analysis_ids:
        return []
    statement = select(NegotiationPositionAnalysis).where(
        col(NegotiationPositionAnalysis.brokerage_id) == brokerage_id,
        col(NegotiationPositionAnalysis.id).in_(list(position_analysis_ids)),
        col(NegotiationPositionAnalysis.invalidated_at).is_(None),
    )
    return list(session.execute(statement).scalars().all())


def list_card_evidence(
    session: Session, brokerage_id: int, position_analysis_id: int
) -> list[NegotiationPositionEvidence]:
    """카드 항목별 근거를 안정된 표시 순서로 조회한다."""
    statement = (
        select(NegotiationPositionEvidence)
        .where(
            col(NegotiationPositionEvidence.brokerage_id) == brokerage_id,
            col(NegotiationPositionEvidence.position_analysis_id) == position_analysis_id,
        )
        .order_by(
            col(NegotiationPositionEvidence.field_name).asc(),
            col(NegotiationPositionEvidence.display_order).asc(),
            col(NegotiationPositionEvidence.id).asc(),
        )
    )
    return list(session.execute(statement).scalars().all())


def find_position_card(
    session: Session, brokerage_id: int, position_analysis_id: int
) -> NegotiationPositionAnalysis | None:
    """피드백 대상 포지션 카드를 사무소 범위에서 조회한다."""
    statement = select(NegotiationPositionAnalysis).where(
        col(NegotiationPositionAnalysis.brokerage_id) == brokerage_id,
        col(NegotiationPositionAnalysis.id) == position_analysis_id,
    )
    return session.execute(statement).scalars().first()


def count_covered_anchors(
    session: Session,
    brokerage_id: int,
    listing_ids: set[int],
    requirement_ids: set[int],
) -> tuple[int, int]:
    """무효화되지 않은 카드를 가진 앵커 수. 백필 전후 확인용이다."""

    def covered(column, identifiers: set[int]) -> int:
        if not identifiers:
            return 0
        return len(
            set(
                session.exec(
                    select(column).where(
                        col(NegotiationPositionAnalysis.brokerage_id) == brokerage_id,
                        col(NegotiationPositionAnalysis.invalidated_at).is_(None),
                        column.in_(sorted(identifiers)),
                    )
                ).all()
            )
        )

    return (
        covered(col(NegotiationPositionAnalysis.listing_id), listing_ids),
        covered(col(NegotiationPositionAnalysis.requirement_id), requirement_ids),
    )
