from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

from sqlalchemy import CursorResult, func, update
from sqlmodel import Session, col, select

from domain.agent_execution.models import (
    AgentRun,
    AiDecisionFeedback,
    MatchCandidateEvaluation,
    MatchCandidateEvidence,
    MatchEvaluation,
    NegotiationPositionAnalysis,
)

from .runs import find_root_cross_judgment_run


def find_match_evaluation_for_run(
    session: Session, brokerage_id: int, agent_run_id: int
) -> MatchEvaluation | None:
    """이 실행의 판정 헤더. 재선점으로 같은 단계가 다시 돌 때 중복 생성을 막는다."""
    statement = select(MatchEvaluation).where(
        col(MatchEvaluation.brokerage_id) == brokerage_id,
        col(MatchEvaluation.agent_run_id) == agent_run_id,
    )
    return session.execute(statement).scalars().first()


def insert_match_evaluation(session: Session, header: MatchEvaluation) -> MatchEvaluation:
    session.add(header)
    session.flush()
    return header


def update_match_evaluation_selection(
    session: Session,
    brokerage_id: int,
    match_evaluation_id: int,
    *,
    anchor_position_analysis_id: int,
    candidate_count: int,
    candidate_selection_snapshot: dict[str, Any],
) -> int:
    """재선점으로 후보를 다시 뽑았을 때 헤더를 갱신한다. 바꾼 행 수를 돌려준다."""
    statement = (
        update(MatchEvaluation)
        .where(
            col(MatchEvaluation.brokerage_id) == brokerage_id,
            col(MatchEvaluation.id) == match_evaluation_id,
        )
        .values(
            anchor_position_analysis_id=anchor_position_analysis_id,
            candidate_count=candidate_count,
            candidate_selection_snapshot=candidate_selection_snapshot,
        )
        .execution_options(synchronize_session=False)
    )
    return cast(CursorResult[Any], session.execute(statement)).rowcount


def update_match_evaluation_snapshot(
    session: Session,
    brokerage_id: int,
    match_evaluation_id: int,
    *,
    candidate_selection_snapshot: dict[str, Any],
) -> int:
    """후보 snapshot 만 갱신한다. 후보 카드 ID 를 붙일 때 쓴다. 바꾼 행 수를 돌려준다."""
    statement = (
        update(MatchEvaluation)
        .where(
            col(MatchEvaluation.brokerage_id) == brokerage_id,
            col(MatchEvaluation.id) == match_evaluation_id,
        )
        .values(candidate_selection_snapshot=candidate_selection_snapshot)
        .execution_options(synchronize_session=False)
    )
    return cast(CursorResult[Any], session.execute(statement)).rowcount


def count_match_candidate_evaluations(
    session: Session, brokerage_id: int, match_evaluation_id: int
) -> int:
    """이미 저장된 후보 판정 수. 중복 저장을 막는 방어 확인이다."""
    statement = select(func.count()).where(
        col(MatchCandidateEvaluation.brokerage_id) == brokerage_id,
        col(MatchCandidateEvaluation.match_evaluation_id) == match_evaluation_id,
    )
    return int(session.execute(statement).scalar_one())


def insert_match_candidate_evaluation(
    session: Session, candidate: MatchCandidateEvaluation
) -> MatchCandidateEvaluation:
    session.add(candidate)
    session.flush()
    return candidate


def insert_match_candidate_evidence(
    session: Session, evidence: Sequence[MatchCandidateEvidence]
) -> None:
    if evidence:
        session.add_all(list(evidence))
        session.flush()


def finalize_match_evaluation(
    session: Session,
    brokerage_id: int,
    match_evaluation_id: int,
    *,
    candidate_count: int,
) -> int:
    """판정을 마친 헤더의 후보 수를 확정한다. 바꾼 행 수를 돌려준다."""
    statement = (
        update(MatchEvaluation)
        .where(
            col(MatchEvaluation.brokerage_id) == brokerage_id,
            col(MatchEvaluation.id) == match_evaluation_id,
        )
        .values(candidate_count=candidate_count, generated_at=func.now())
        .execution_options(synchronize_session=False)
    )
    return cast(CursorResult[Any], session.execute(statement)).rowcount


def find_anchor_card_for_run(
    session: Session, brokerage_id: int, run_id: int
) -> NegotiationPositionAnalysis | None:
    """실행이 확보한 활성 앵커만 조회한다. 헤더가 있으면 그 참조가 정본이다."""
    header = find_match_evaluation_for_run(session, brokerage_id, run_id)
    run = find_root_cross_judgment_run(session, brokerage_id, run_id) if header is None else None
    return find_anchor_card_from_context(session, brokerage_id, run, header)


def find_anchor_card_from_context(
    session: Session,
    brokerage_id: int,
    run: AgentRun | None,
    header: MatchEvaluation | None,
) -> NegotiationPositionAnalysis | None:
    """Reuse already loaded result context instead of reading its full JSONB twice."""
    if header is not None:
        if header.brokerage_id != brokerage_id:
            return None
        position_analysis_id = header.anchor_position_analysis_id
    else:
        if run is None or run.brokerage_id != brokerage_id:
            return None
        position_analysis_id = run.redacted_output_snapshot.get("position_analysis_id")
    if not isinstance(position_analysis_id, int):
        return None
    return (
        session.execute(
            select(NegotiationPositionAnalysis).where(
                col(NegotiationPositionAnalysis.brokerage_id) == brokerage_id,
                col(NegotiationPositionAnalysis.id) == position_analysis_id,
                col(NegotiationPositionAnalysis.invalidated_at).is_(None),
            )
        )
        .scalars()
        .first()
    )


def list_candidate_judgments(
    session: Session,
    brokerage_id: int,
    match_evaluation_id: int,
    *,
    candidate_card_ids: Sequence[int] | None = None,
) -> list[MatchCandidateEvaluation]:
    """판정된 후보를 기각 후보까지 포함해 순위 순으로 조회한다."""
    statement = (
        select(MatchCandidateEvaluation)
        .where(
            col(MatchCandidateEvaluation.brokerage_id) == brokerage_id,
            col(MatchCandidateEvaluation.match_evaluation_id) == match_evaluation_id,
        )
        .order_by(col(MatchCandidateEvaluation.match_rank).asc())
    )
    if candidate_card_ids is not None:
        if not candidate_card_ids:
            return []
        statement = statement.where(
            col(MatchCandidateEvaluation.candidate_position_analysis_id).in_(
                list(candidate_card_ids)
            )
        )
    return list(session.execute(statement).scalars().all())


def list_candidate_judgment_evidence(
    session: Session, brokerage_id: int, candidate_evaluation_ids: Sequence[int]
) -> list[MatchCandidateEvidence]:
    """후보 판정 근거를 한 번에 조회해 후보별 N+1 질의를 피한다."""
    if not candidate_evaluation_ids:
        return []
    statement = (
        select(MatchCandidateEvidence)
        .where(
            col(MatchCandidateEvidence.brokerage_id) == brokerage_id,
            col(MatchCandidateEvidence.match_candidate_evaluation_id).in_(
                list(candidate_evaluation_ids)
            ),
        )
        .order_by(col(MatchCandidateEvidence.id).asc())
    )
    return list(session.execute(statement).scalars().all())


def find_candidate_judgment(
    session: Session, brokerage_id: int, candidate_evaluation_id: int
) -> MatchCandidateEvaluation | None:
    """피드백 대상 후보 판정을 사무소 범위에서 조회한다."""
    statement = select(MatchCandidateEvaluation).where(
        col(MatchCandidateEvaluation.brokerage_id) == brokerage_id,
        col(MatchCandidateEvaluation.id) == candidate_evaluation_id,
    )
    return session.execute(statement).scalars().first()


def add_decision_feedback(session: Session, feedback: AiDecisionFeedback) -> AiDecisionFeedback:
    session.add(feedback)
    session.flush()
    return feedback
