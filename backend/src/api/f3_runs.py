from __future__ import annotations

from fastapi import APIRouter, Depends, Path
from sqlmodel import Session

from api.schemas.f3_runs import F3RunCreateRequest, F3RunResponse, F3RunStatusResponse
from domain.agent_execution import service
from domain.authentication.dependencies import get_current_user, require_csrf
from domain.authentication.models import CurrentUser
from domain.session import get_db_session

router = APIRouter(prefix="/f3", tags=["agent-execution"])


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
