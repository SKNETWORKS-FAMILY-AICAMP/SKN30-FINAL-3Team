from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

# v1 은 상담 로그 집합을 MAX(interaction_at) 하나로만 대표해서, 과거 시각 로그를 추가하거나
# 로그를 무효화해도 키가 그대로였다. v2 는 건수와 최대 로그 ID 를 함께 넣어 집합 변화를 잡았다.
# v3 은 여기에 모델 입력 전체의 지문과 범위 지문을 더한다. 앵커 `row_version` 은 세대 스펙,
# 단지명, 당사자 역할, 날짜 신호가 바뀌어도 그대로여서 그것만으로는 캐시를 못 믿는다.
CACHE_KEY_SCHEMA_VERSION = "position-card:v3"


def _utc(moment: datetime | None) -> str | None:
    """같은 시각이면 표기가 달라도 같은 문자열이 되게 한다. 없는 값은 null 로 둔다."""
    if moment is None:
        return None
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        # 로컬 timezone 으로 암묵 변환하면 서버마다 다른 키가 나온다.
        raise ValueError("last_interaction_at must be timezone-aware")
    return moment.astimezone(UTC).isoformat()


def position_card_cache_key(
    *,
    brokerage_id: int,
    negotiation_side: str,
    anchor_type: str,
    anchor_id: int,
    data_version: int,
    interaction_count: int,
    last_interaction_at: datetime | None,
    max_interaction_id: int | None,
    agent_type: str,
    model_config_id: int | None,
    prompt_version: str | None,
    workflow_version: str | None,
    input_fingerprint: str,
    scope_identity: str,
) -> str:
    """포지션 카드 캐시 키. DB 와 전역 상태에 의존하지 않는 순수 함수다.

    아직 정해지지 않은 모델·프롬프트·워크플로 버전은 가짜 값으로 채우지 않고 null 그대로
    키에 넣는다. 나중에 값이 생기면 키가 자연히 달라져 캐시가 무효화된다.
    """
    payload = {
        "schema": CACHE_KEY_SCHEMA_VERSION,
        "brokerage_id": brokerage_id,
        "negotiation_side": negotiation_side,
        "anchor_type": anchor_type,
        "anchor_id": anchor_id,
        "data_version": data_version,
        "interaction_count": interaction_count,
        "last_interaction_at": _utc(last_interaction_at),
        "max_interaction_id": max_interaction_id,
        "agent_type": agent_type,
        "model_config_id": model_config_id,
        "prompt_version": prompt_version,
        "workflow_version": workflow_version,
        # 지문은 이미 digest 라 원문이 키에 들어가지 않는다.
        "input_fingerprint": input_fingerprint,
        "scope_identity": scope_identity,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"{CACHE_KEY_SCHEMA_VERSION}:{digest}"
