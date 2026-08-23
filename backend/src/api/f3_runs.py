from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query
from sqlmodel import Session

from api.schemas.f3_runs import (
    F3FeedbackCreateRequest,
    F3FeedbackResponse,
    F3RunCreateRequest,
    F3RunResponse,
    F3RunResultResponse,
    F3RunStatusResponse,
)
from domain.agent_execution import feedback as feedback_service
from domain.agent_execution import results, service
from domain.authentication.dependencies import get_current_user, require_csrf
from domain.authentication.models import CurrentUser
from domain.session import get_db_session

router = APIRouter(prefix="/f3", tags=["agent-execution"])

# 결과 조회 한 페이지의 후보 수. 후보 목록은 전체 후보를 대상으로 페이징한다.
DEFAULT_CANDIDATE_LIMIT = 20
MAX_CANDIDATE_LIMIT = 100


@router.post("/runs", response_model=F3RunResponse, status_code=202)
def create_f3_run(
    payload: F3RunCreateRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db_session),
    _: None = Depends(require_csrf),
) -> F3RunResponse:
    """교차 판정 실행을 적재한다.

    같은 앵커·입력 버전의 재사용 가능한 실행이 있으면 새로 만들지 않고 그 실행을 돌려준다
    (F3-CR-12). 재사용이든 신규든 응답 형태는 같다.
    """
    queued = service.queue_cross_judgment_run(
        db, user.brokerage_id, user.id, payload.anchor_type, payload.anchor_id
    )
    return F3RunResponse.from_domain(queued.run)


@router.get("/runs/{run_id}", response_model=F3RunStatusResponse)
def get_f3_run(
    run_id: int = Path(ge=1),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> F3RunStatusResponse:
    run = service.require_cross_judgment_run(db, user.brokerage_id, run_id)
    return F3RunStatusResponse.from_domain(run)


@router.get("/runs/{run_id}/result", response_model=F3RunResultResponse)
def get_f3_run_result(
    run_id: int = Path(ge=1),
    limit: int = Query(default=DEFAULT_CANDIDATE_LIMIT, ge=1, le=MAX_CANDIDATE_LIMIT),
    offset: int = Query(default=0, ge=0),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> F3RunResultResponse:
    """실행의 현재 결과를 조회한다.

    진행 중이면 확보된 데까지만 채운다. 빈 패널을 유지하지 않고 마지막 안전 단계를 보여준다
    (F3-CR-09). 상태를 바꾸지 않는 GET 이므로 CSRF 토큰을 요구하지 않는다.
    """
    result = results.load_run_result(db, user.brokerage_id, run_id, limit=limit, offset=offset)
    return F3RunResultResponse.from_domain(result)


@router.post("/feedback", response_model=F3FeedbackResponse, status_code=201)
def create_f3_feedback(
    payload: F3FeedbackCreateRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db_session),
    _: None = Depends(require_csrf),
) -> F3FeedbackResponse:
    """포지션 카드 또는 중개 판정 후보에 대한 피드백을 남긴다 (F3-TR-03).

    사무소와 작성자는 세션에서만 도출한다. 다른 사무소의 대상은 없는 것과 같은 404 다.
    """
    stored = feedback_service.record_feedback(
        db,
        user.brokerage_id,
        user.id,
        target=payload.target,
        target_id=payload.target_id,
        feedback_type=payload.feedback_type,
        reason=payload.reason,
        field_name=payload.field_name,
        corrected_value=payload.corrected_value,
        detail=payload.detail,
    )
    return F3FeedbackResponse.from_domain(stored)
