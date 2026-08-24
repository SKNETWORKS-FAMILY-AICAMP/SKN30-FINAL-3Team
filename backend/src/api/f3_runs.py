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
from domain.agent_execution import feedback, results, service
from domain.authentication.dependencies import get_current_user, require_csrf
from domain.authentication.models import CurrentUser
from domain.session import get_db_session

router = APIRouter(prefix="/f3", tags=["agent-execution"])

DEFAULT_CANDIDATE_LIMIT = 20
MAX_CANDIDATE_LIMIT = 100


@router.post("/feedback", response_model=F3FeedbackResponse, status_code=201)
def create_f3_feedback(
    payload: F3FeedbackCreateRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db_session),
    _: None = Depends(require_csrf),
) -> F3FeedbackResponse:
    stored = feedback.record_not_interested_feedback(
        db,
        user.brokerage_id,
        user.id,
        payload.target,
        payload.target_id,
        payload.reason,
        payload.field_name,
    )
    return F3FeedbackResponse.from_domain(stored)


@router.post("/runs", response_model=F3RunResponse, status_code=202)
def create_f3_run(
    payload: F3RunCreateRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db_session),
    _: None = Depends(require_csrf),
) -> F3RunResponse:
    run = service.queue_cross_judgment_run(
        db, user.brokerage_id, user.id, payload.anchor_type, payload.anchor_id
    )
    return F3RunResponse.from_domain(run)


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
    """실행의 현재 결과를 전체 SQL 후보 기준 페이지로 조회한다."""
    result = results.load_run_result(db, user.brokerage_id, run_id, limit=limit, offset=offset)
    return F3RunResultResponse.from_domain(result)
