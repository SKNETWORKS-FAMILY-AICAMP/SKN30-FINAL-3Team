"""모델 입력 전체의 결정적 지문.

`agent_run.input_data_version`은 앵커 한 행의 `row_version`이다. 그 값만으로는 세대 스펙,
단지명, 당사자 역할, 상담 로그 집합, 날짜 신호처럼 모델 입력에 실제로 들어가는 나머지가
바뀌었는지 알 수 없다. 그래서 **AI에 넘긴 요청 그 자체**를 정규화해 digest 하나로 만든다.

지문은 digest만 남긴다. 원문과 개인정보는 DB, 로그, 오류 어디에도 넣지 않는다.

Python `hash()`는 쓰지 않는다. 프로세스마다 값이 달라 캐시와 fencing에 쓸 수 없다.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC
from typing import Any

from brokerage_ai.f3 import PositionCardGenerationRequest

# 정규화 방식이 바뀌면 이 값을 올린다. 지문의 의미가 달라졌음을 키에서 드러내기 위해서다.
INPUT_FINGERPRINT_SCHEMA_VERSION = "position-card-input:v1"

# 순서가 의미 없는 집합. 조회 순서가 달라져도 같은 지문이 나오게 명시적으로 정렬한다.
_UNORDERED_ANCHOR_FIELDS = ("party_roles",)


def _canonical_payload(request: PositionCardGenerationRequest) -> dict[str, Any]:
    """지문에 넣을 정규 표현.

    `model_dump(mode="json")`이 Decimal·datetime·date·enum·None의 직렬화를 한 가지로 고정한다.
    Decimal은 문자열, 시각은 ISO 8601, enum은 값, None은 null이 된다.

    `as_of`만 날짜로 줄인다. 정확한 시각을 그대로 넣으면 모든 실행이 서로 다른 지문이 되어
    캐시가 통째로 무의미해진다. 날짜 단위 bucket 은 같은 날 재실행은 재사용하고 다음 날에는
    낡은 `days_since`·`days_until` 카드를 다시 만들게 한다.
    """
    payload: dict[str, Any] = request.model_dump(mode="json")
    payload["schema"] = INPUT_FINGERPRINT_SCHEMA_VERSION
    payload["date_signals"]["as_of"] = as_of_bucket(request)

    anchor = payload.get("anchor")
    if isinstance(anchor, dict):
        for field in _UNORDERED_ANCHOR_FIELDS:
            values = anchor.get(field)
            if isinstance(values, list):
                anchor[field] = sorted(
                    values, key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False)
                )
    return payload


def as_of_bucket(request: PositionCardGenerationRequest) -> str:
    """날짜 신호의 캐시 bucket. UTC 날짜 하나로 고정한다."""
    return request.date_signals.as_of.astimezone(UTC).date().isoformat()


def input_fingerprint(request: PositionCardGenerationRequest) -> str:
    """이 요청과 정확히 같은 입력에서만 같은 값이 나오는 지문."""
    canonical = json.dumps(
        _canonical_payload(request), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"{INPUT_FINGERPRINT_SCHEMA_VERSION}:{digest}"
