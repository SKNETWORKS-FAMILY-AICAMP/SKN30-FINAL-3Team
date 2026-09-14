from __future__ import annotations

from typing import Any, cast

from sqlalchemy import CursorResult, func, text, update
from sqlmodel import Session, col, select

from domain.agent_execution.models import (
    BROKERAGE_JUDGMENT_CAPABILITY,
    POSITION_CARD_CAPABILITY,
    RUNNING_STATUS,
    AgentRun,
    AiModelConfig,
)

from .runs import root_cross_judgment_conditions

# model snapshot 에 담아도 되는 값. endpoint 전체 URL, API key, token 은 목록에 없다.
MODEL_SNAPSHOT_FIELDS = (
    "provider",
    "model_name",
    "model_version",
    "endpoint_alias",
    "config_key",
    "config_version",
)


def find_model_config(
    session: Session, brokerage_id: int, model_config_id: int, capability: str
) -> AiModelConfig | None:
    """이 사무소의 해당 capability 활성 설정만 돌려준다.

    다른 사무소의 설정과 다른 용도의 설정은 여기서 걸러진다. 호출자는 `None` 을 존재 여부를
    드러내지 않는 하나의 오류로 바꾼다.
    """
    statement = select(AiModelConfig).where(
        col(AiModelConfig.brokerage_id) == brokerage_id,
        col(AiModelConfig.id) == model_config_id,
        col(AiModelConfig.capability) == capability,
        col(AiModelConfig.is_active).is_(True),
    )
    return session.execute(statement).scalars().first()


def find_active_model_config(
    session: Session, brokerage_id: int, capability: str
) -> AiModelConfig | None:
    """사무소와 capability가 같은 최신 활성 모델 설정을 돌려준다.

    Provider와 모델 이름은 환경이나 Worker 코드의 기본값이 아니라 이 설정 행에서 결정한다.
    같은 capability의 활성 설정이 여러 개면 가장 높은 config version을 사용한다.
    """
    statement = (
        select(AiModelConfig)
        .where(
            col(AiModelConfig.brokerage_id) == brokerage_id,
            col(AiModelConfig.capability) == capability,
            col(AiModelConfig.is_active).is_(True),
        )
        .order_by(col(AiModelConfig.config_version).desc(), col(AiModelConfig.id).desc())
        .limit(1)
    )
    return session.execute(statement).scalars().first()


def find_position_card_model_config(
    session: Session, brokerage_id: int, model_config_id: int
) -> AiModelConfig | None:
    """포지션 카드 생성용 설정."""
    return find_model_config(session, brokerage_id, model_config_id, POSITION_CARD_CAPABILITY)


def find_brokerage_judgment_model_config(
    session: Session, brokerage_id: int, model_config_id: int
) -> AiModelConfig | None:
    """중개 판정용 설정. 대리와 판정은 다른 모델일 수 있다 (F3-NF-10)."""
    return find_model_config(session, brokerage_id, model_config_id, BROKERAGE_JUDGMENT_CAPABILITY)


def safe_model_snapshot(config: AiModelConfig) -> dict[str, object]:
    """DB 설정에서 allowlist 필드만 뽑는다. 호출자가 준 임의 dict 를 그대로 쓰지 않는다."""
    return {field: getattr(config, field) for field in MODEL_SNAPSHOT_FIELDS}


def bind_run_execution_configuration(
    session: Session,
    run_id: int,
    brokerage_id: int,
    worker_id: str,
    attempt_count: int,
    *,
    model_config_id: int,
    model_snapshot: dict[str, object],
    prompt_version: str,
    workflow_version: str,
    expected_status: str = RUNNING_STATUS,
) -> int:
    """실행에 모델·프롬프트·워크플로 바인딩을 처음 기록한다.

    lease fencing 아래에서 네 값을 한 번에 쓴다. 미바인딩은 세 버전 컬럼이 NULL 이고
    `model_snapshot` 이 빈 객체인 상태뿐이다. 일부만 채워진 행은 `WHERE` 가 걸러내 조용히
    덮이지 않는다. 바꾼 행 수를 돌려준다.
    """
    statement = (
        update(AgentRun)
        .where(
            *root_cross_judgment_conditions(),
            col(AgentRun.id) == run_id,
            col(AgentRun.brokerage_id) == brokerage_id,
            col(AgentRun.status) == expected_status,
            col(AgentRun.lease_owner) == worker_id,
            col(AgentRun.attempt_count) == attempt_count,
            col(AgentRun.lease_expires_at) > func.now(),
            col(AgentRun.model_config_id).is_(None),
            col(AgentRun.prompt_version).is_(None),
            col(AgentRun.workflow_version).is_(None),
            # model_snapshot 은 NOT NULL DEFAULT '{}' 이라 "NULL 이면 미바인딩"이 성립하지
            # 않는다. 빈 객체인지 JSONB 로 직접 비교한다.
            text("agent_run.model_snapshot::jsonb = '{}'::jsonb"),
        )
        .values(
            model_config_id=model_config_id,
            model_snapshot=model_snapshot,
            prompt_version=prompt_version,
            workflow_version=workflow_version,
            updated_at=func.now(),
        )
        .execution_options(synchronize_session=False)
    )
    return cast(CursorResult[Any], session.execute(statement)).rowcount
