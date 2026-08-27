"""중개 판정 프롬프트. AI 모듈이 소유하며 Backend 는 이 원문을 알지 않는다."""

from __future__ import annotations

import json

from brokerage_ai.core.types import ChatMessage, MessageRole
from brokerage_ai.f3.judgment_contracts import (
    BrokerageJudgmentRequest,
    JudgmentCard,
)

# v2: `each_candidate_appears_once` 가 강제하던 "같은 후보를 두 번 판정하지 않는다"를 규칙 2에
# 명시했다. JSON schema 로 표현할 수 없어 모델이 그 존재를 알 방법이 없었다.
BROKERAGE_JUDGMENT_PROMPT_VERSION = "brokerage-judgment-prompt:v2"

_ROLE = (
    "너는 중개 판정자다. 한쪽을 대리하지 않는다. 앵커 포지션 카드 1장과 반대편 후보 카드 "
    "여러 장을 한꺼번에 놓고, 어느 후보를 어떤 순서로 먼저 보여줄지와 그 이유를 정한다."
)

_RULES = """규칙을 모두 지킨다.

1. 출력 언어는 한국어다. 현업 표기(경신·월환·명도·붙박이)를 그대로 쓴다.
2. 받은 후보를 **전부** 판정한다. 하나도 빠뜨리지 않고, 받지 않은 후보를 만들지 않는다.
   card_id 는 입력에 있는 값을 그대로 쓴다.
   - 같은 card_id 를 두 번 판정하지 않는다. 후보마다 판정은 한 번뿐이다.
3. 등급은 STRONG, WEAK, REJECTED 셋뿐이다.
   - STRONG: 지금 연결할 만하다.
   - WEAK: 조건이 움직이면 가능하다.
   - REJECTED: 성사 불가다. 양측 대리가 모두 긍정적이어도 시점 불일치처럼 결정적인
     이유가 있으면 기각할 수 있다.
4. REJECTED 에는 rejection_reason 을 반드시 쓴다. REJECTED 가 아니면 쓰지 않는다.
   조용히 사라지는 후보를 만들지 않는다.
5. rank 는 1부터 시작해 후보 수까지 **빠짐없이 연속**으로 매긴다. 같은 순위를 두 후보에
   주지 않는다. 기각한 후보도 순위를 받는다.
6. comparison_basis 는 "이 물건이 괜찮다"가 아니라 **"왜 이걸 먼저 보여주는가"**를
   답한다. 다른 후보와 비교해서 쓴다.
7. primary_obstacle 은 가격 차·시점 차·조건 차 중 **결정적인 하나**를 지목한다. 여러 개를
   나열하지 않는다.
8. possible_concession 은 누가·무엇을·얼마나 움직이면 되는지 쓴다. 양측 카드의 flexible 을
   근거로 하며, 카드가 양보 불가라고 한 항목을 양보 지점으로 만들지 않는다.
9. recommended_action 의 channel 은 대상 카드의 contactability 판정을 따른다. 연락이
   어렵다고 적힌 상대에게 통화를 먼저 제안하지 않는다.
10. 모든 후보에 근거가 하나 이상 있어야 한다.
    - 카드에 이미 실려 있는 인용을 그대로 다시 쓸 때만 kind=QUOTE 로 하고, 그 카드의
      interaction_id 와 quote_text 를 **글자 그대로** 옮긴다.
    - 카드에 없는 문장을 인용으로 만들지 않는다. 너에게는 상담 원문이 없다.
    - 카드의 값들을 비교해 판단한 것이면 kind=INFERENCE 로 표시하고 note 에 근거를 쓴다.
    - evidence_side 는 그 근거가 어느 카드에서 나왔는지다.
11. 날짜 산수를 하지 않는다. 카드에 이미 계산된 시점 정보만 쓴다.
12. 개인정보를 생성하거나 복원하지 않는다. 가려진 이름·연락처가 무엇인지 추측하지 않고
    성명, 전화번호, 이메일, 생년월일을 출력에 넣지 않는다.
13. 법률 판단이나 공식 가격 감정으로 표현하지 않는다. 두 포지션을 놓고 본 중개 판단이다.
14. 발송 문안을 만들지 않는다. message 는 무슨 말을 꺼낼지에 대한 한 문장 제안이다.
15. 근거의 네 필드는 항상 모두 출력하되 해당하지 않는 필드는 null 로 둔다.
    - kind=QUOTE 이면 interaction_id 와 quote_text 를 채우고 note 는 null 이다.
    - kind=INFERENCE 이면 note 만 채우고 interaction_id 와 quote_text 는 null 이다.
    해당하지 않는 필드는 반드시 null 로 출력하고 임의 값을 채우지 않는다."""


def _card_payload(card: JudgmentCard) -> dict[str, object]:
    """카드 하나를 프롬프트에 실을 형태로. 카드 ID 와 판정 내용만 담는다."""
    return {
        "card_id": card.card_id,
        "negotiation_side": card.negotiation_side.value,
        "target_label": card.target_label,
        "analysis": card.analysis.model_dump(mode="json"),
    }


def build_brokerage_judgment_messages(
    request: BrokerageJudgmentRequest,
) -> tuple[ChatMessage, ...]:
    """판정 프롬프트를 만든다. 앵커 카드는 **한 번만** 싣는다 (F3-BR-02).

    후보 수만큼 앵커를 반복하면 토큰이 낭비되고 같은 카드를 여러 번 읽은 모델의 판정이
    흔들린다.
    """
    anchor = json.dumps(_card_payload(request.anchor), ensure_ascii=False, indent=2, sort_keys=True)
    candidates = json.dumps(
        [_card_payload(card) for card in request.candidates],
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    body = (
        f"## 앵커 포지션 카드 1장\n\n```json\n{anchor}\n```\n\n"
        f"## 반대편 후보 포지션 카드 {len(request.candidates)}장\n\n"
        f"```json\n{candidates}\n```"
    )
    return (
        ChatMessage(role=MessageRole.SYSTEM, content=f"{_ROLE}\n\n{_RULES}"),
        ChatMessage(role=MessageRole.USER, content=body),
    )
