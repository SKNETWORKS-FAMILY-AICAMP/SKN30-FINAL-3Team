"""포지션 카드 프롬프트. AI 모듈이 소유하며 Backend 는 이 원문을 알지 않는다."""

from __future__ import annotations

import json

from brokerage_ai.core.types import ChatMessage, MessageRole
from brokerage_ai.f3.contracts import (
    ConsultationLogInput,
    NegotiationSide,
    PositionCardGenerationRequest,
)

# v2: JSON schema 로 표현할 수 없는 교차 필드 규칙 셋을 본문에 명시했다. cache key 에 들어가므로
# 이 값을 올리면 v1 프롬프트로 만든 카드가 재사용되지 않는다.
POSITION_CARD_PROMPT_VERSION = "position-card-prompt:v2"

_SIDE_SCOPE = {
    NegotiationSide.LISTING: (
        "너는 매물 대리다. 세대·매물 보유자 측(소유자와 현 임차인)의 입장만 세운다. "
        "손님 측 데이터와 손님 상담 로그는 입력에 없으며 추측하지도 않는다."
    ),
    NegotiationSide.REQUIREMENT: (
        "너는 손님 대리다. 구입장 손님 측의 매수·임차 입장만 세운다. "
        "매물 측 데이터와 소유자 상담 로그는 입력에 없으며 추측하지도 않는다."
    ),
}

_RULES = """규칙을 모두 지킨다.

1. 출력 언어는 한국어다. 현업 표기(경신·월환·명도·붙박이)를 그대로 쓴다.
2. 반대편 당사자의 데이터, 의도, 조건을 추측해서 만들지 않는다.
3. 제공된 상담 로그 **전체**를 시간순으로 고려한다. 최신 몇 건만 골라 쓰지 않는다.
4. 최신 진술이 과거 진술을 이긴다. 이후 로그에서 철회나 정정이 확인되면 그쪽을 따른다.
   매도·매수 의향을 명시적으로 거둔 진술이 있으면 intent 는 WITHDRAWN 이다.
5. 모든 판정 항목에는 근거가 하나 이상 있어야 한다.
   - 로그 원문에 실제로 있는 말이면 kind=QUOTE, 그 로그의 정확한 interaction_id,
     그리고 제시된 본문에서 **그대로 잘라낸 부분 문자열**을 quote_text 에 넣는다.
   - 요약하거나 바꿔 쓰지 않는다. 본문에 없는 문장을 인용으로 만들지 않는다.
   - 로그에 없고 정황으로 판단한 것이면 kind=INFERENCE 로 표시하고 note 에 근거를 쓴다.
6. 로그가 부족해 판단할 수 없으면 억지로 채우지 말고 UNKNOWN 을 쓴다. 판단 불가도 유효한
   판정이다.
   - **상담 로그가 하나도 없으면 kind=QUOTE 를 쓰지 않는다.** 인용할 원문 자체가 없다.
     앵커에 실린 장부 값(금액 원문, 평형 원문, 명도 조건 등)은 상담 로그가 아니므로 인용이
     아니다. 그 값들로 판단했다면 kind=INFERENCE 로 적는다.
7. 가격 추정은 장부 표기 금액과 다를 때만 낸다. 다르면 basis 근거가 반드시 있어야 한다.
   근거를 만들 수 없으면 추정하지 않는다. 장부 표기 금액 자체는 네가 정하지 않는다.
   - price 에 같은 price_kind 를 두 번 담지 않는다. 거래 유형마다 최대 한 번이다.
   - estimated_monthly_amount 는 price_kind 가 MONTHLY_RENT 일 때만 쓴다. 매매와 전세는
     금액 축이 하나뿐이라 이 값을 채우지 않는다.
8. 날짜 산수를 하지 않는다. 남은 일수는 이미 계산되어 date_signals 로 주어진다.
9. hard_deadline 은 date_signals 의 hard_deadline_candidate 와 같은 값이거나 null 이다.
   그 밖의 날짜를 만들지 않는다.
   - **근거 있는 timing constraint 를 하나도 세울 수 없으면 hard_deadline 은 반드시 null 이다.**
     마감일만 단독으로 채우지 않는다. 인용할 로그도 정황 판단도 없으면 마감일도 없다.
10. 개인정보를 생성하거나 복원하지 않는다. 본문의 `*` 는 가려진 이름·연락처이며 그것이
    무엇인지 추측해서 쓰지 않는다. 성명, 전화번호, 이메일, 생년월일을 출력에 넣지 않는다.
11. 법률 판단이나 공식 가격 감정으로 표현하지 않는다. 상담 로그에서 읽어낸 협상 입장이다.
12. contactability 는 연락 **가능 상태**에 대한 판정이다. 실제 연락처를 뜻하지 않으며
    연락처를 note 에 쓰지 않는다.
13. 처분 결정권 제약(임차인이라 결정권이 없음, 공동명의라 단독 결정 불가, 의뢰인이 실질
    결정권자가 아님)은 별도 항목이 아니라 inflexible 에 근거와 함께 적는다.
14. 입력이 길더라도 과거 로그를 조용히 버리지 않는다. 전부 읽고 판단한다.
15. 근거의 네 필드는 항상 모두 출력하되 해당하지 않는 필드는 null 로 둔다.
    - kind=QUOTE 이면 interaction_id 와 quote_text 를 채우고 note 는 null 이다.
    - kind=INFERENCE 이면 note 만 채우고 interaction_id 와 quote_text 는 null 이다.
    해당하지 않는 필드는 반드시 null 로 출력하고 임의 값을 채우지 않는다."""


def _log_line(log: ConsultationLogInput) -> str:
    parts = [f"[{log.interaction_id}]", log.interaction_at.isoformat(), log.channel]
    if log.counterparty_role:
        parts.append(log.counterparty_role)
    if log.interaction_result:
        parts.append(log.interaction_result)
    return f"{' · '.join(parts)}\n{log.masked_content}"


def _anchor_payload(request: PositionCardGenerationRequest) -> dict[str, object]:
    """앵커와 날짜 신호만 담는다. source identity 와 계약 버전은 모델의 일이 아니다."""
    anchor = request.anchor.model_dump(mode="json")
    anchor.pop("negotiation_side", None)
    return {
        "anchor_type": request.negotiation_side.value,
        "anchor": anchor,
        "date_signals": request.date_signals.model_dump(mode="json"),
    }


def build_position_card_messages(
    request: PositionCardGenerationRequest,
) -> tuple[ChatMessage, ...]:
    """대리 프롬프트를 만든다. 상담 로그는 항상 전량을 시간순으로 싣는다."""
    logs = sorted(
        request.consultation_logs, key=lambda log: (log.interaction_at, log.interaction_id)
    )
    body = json.dumps(_anchor_payload(request), ensure_ascii=False, indent=2, sort_keys=True)
    if logs:
        rendered = "\n\n".join(_log_line(log) for log in logs)
        log_section = f"## 상담 로그 {len(logs)}건 (오래된 순)\n\n{rendered}"
    else:
        log_section = (
            "## 상담 로그 0건\n\n상담 로그가 없다. 로그 근거가 필요한 항목은 UNKNOWN 으로 둔다."
        )

    side = NegotiationSide(request.negotiation_side)
    return (
        ChatMessage(role=MessageRole.SYSTEM, content=f"{_SIDE_SCOPE[side]}\n\n{_RULES}"),
        ChatMessage(
            role=MessageRole.USER,
            content=f"## 장부 사실과 날짜 신호\n\n```json\n{body}\n```\n\n{log_section}",
        ),
    )
