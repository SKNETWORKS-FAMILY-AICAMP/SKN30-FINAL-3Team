"""F3 비서 에이전트의 HTTP 표면.

두 경로 모두 상태를 바꾼다 — 카드와 판정 결과가 저장되고 `agent_run` 이 남는다.
그래서 POST 이고 CSRF 토큰을 요구한다. `brokerage_id` 는 세션에서만 도출한다.
"""

from __future__ import annotations

from brokerage_ai.providers.registry import ProviderRegistry
from fastapi import APIRouter, Depends
from sqlmodel import Session

from api.schemas.negotiation import (
    MatchEvaluationCreateRequest,
    MatchEvaluationResponse,
    PositionCardCreateRequest,
    PositionCardResponse,
)
from core.ai import get_provider_registry
from domain.authentication.dependencies import get_current_user, require_csrf
from domain.authentication.models import CurrentUser
from domain.negotiation import service
from domain.session import get_db_session

router = APIRouter(tags=["negotiation"])


@router.post("/position-cards", response_model=PositionCardResponse, status_code=201)
def create_position_card(
    payload: PositionCardCreateRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db_session),
    registry: ProviderRegistry = Depends(get_provider_registry),
    _: None = Depends(require_csrf),
) -> PositionCardResponse:
    """[저장] 트리거 — 자기 쪽 대리 1회. 후보 조회도 중개 판정도 하지 않는다."""
    outcome = service.create_position_card(
        db,
        registry,
        brokerage_id=user.brokerage_id,
        user_id=user.id,
        unit_id=payload.unit_id,
        requirement_id=payload.requirement_id,
    )
    return PositionCardResponse.from_domain(outcome)


@router.post("/match-evaluations", response_model=MatchEvaluationResponse, status_code=201)
def create_match_evaluation(
    payload: MatchEvaluationCreateRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db_session),
    registry: ProviderRegistry = Depends(get_provider_registry),
    _: None = Depends(require_csrf),
) -> MatchEvaluationResponse:
    """[찾기] 트리거 — 후보 추출·카드 확보·중개 판정·등급 산출.

    기각 후보도 응답에 포함한다. 판정 수 = 노출 수 + 기각 수 (수용 기준 9).
    """
    outcome = service.evaluate_matches(
        db,
        registry,
        brokerage_id=user.brokerage_id,
        user_id=user.id,
        requirement_id=payload.requirement_id,
        as_of=payload.as_of,
        case_key=payload.case_key,
    )
    return MatchEvaluationResponse.from_domain(outcome)
