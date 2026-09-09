"""F3 조회 adapter. 화면 열기·새로고침은 작업을 생성하지 않는다."""

from typing import Literal

from fastapi import APIRouter, Depends, Path, Query, Response
from sqlmodel import Session

from api.schemas.f3_judgments import (
    F3JudgmentDetailResponse,
    F3JudgmentListResponse,
    F3JudgmentTargetResponse,
)
from domain.agent_execution import judgment_queries
from domain.agent_execution.models import AnchorType
from domain.authentication.dependencies import get_current_user
from domain.authentication.models import CurrentUser
from domain.session import get_db_session

router = APIRouter(prefix="/f3", tags=["agent-execution"])
FilterName = Literal["HAS_MATCH", "HAS_STRONG", "HAS_UNJUDGED", "NEEDS_ATTENTION", "ALL"]


@router.get("/judgment-results", response_model=F3JudgmentListResponse)
def list_results(
    response: Response,
    anchor_type: AnchorType,
    filter: FilterName = Query(default="HAS_MATCH"),
    trade_type: str | None = Query(default=None, max_length=30),
    complex_id: int | None = Query(default=None, ge=1),
    assignee_id: int | None = Query(default=None, ge=1),
    q: str | None = Query(default=None, max_length=100),
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> F3JudgmentListResponse:
    response.headers["Cache-Control"] = "no-store"
    return F3JudgmentListResponse.model_validate(
        judgment_queries.list_judgments(
            db,
            user.brokerage_id,
            anchor_type,
            filter_name=filter,
            trade_type=trade_type,
            complex_id=complex_id,
            assignee_id=assignee_id,
            q=q,
            cursor=cursor,
            limit=limit,
        )
    )


@router.get("/judgment-targets/{anchor_type}/{anchor_id}", response_model=F3JudgmentTargetResponse)
def get_target(
    response: Response,
    anchor_type: AnchorType,
    anchor_id: int = Path(ge=1),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> F3JudgmentTargetResponse:
    response.headers["Cache-Control"] = "no-store"
    return F3JudgmentTargetResponse.model_validate(
        judgment_queries.get_target(db, user.brokerage_id, anchor_type, anchor_id)
    )


@router.get("/judgment-results/{result_id}", response_model=F3JudgmentDetailResponse)
def get_result(
    response: Response,
    result_id: int = Path(ge=1),
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=20, ge=1, le=100),
    candidate_id: int | None = Query(default=None, ge=1),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db_session),
) -> F3JudgmentDetailResponse:
    response.headers["Cache-Control"] = "no-store"
    return F3JudgmentDetailResponse.model_validate(
        judgment_queries.get_judgment(
            db, user.brokerage_id, result_id, cursor=cursor, limit=limit, candidate_id=candidate_id
        )
    )
