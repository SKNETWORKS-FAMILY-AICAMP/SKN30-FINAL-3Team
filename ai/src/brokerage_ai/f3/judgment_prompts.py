"""중개 판정 프롬프트. AI 모듈이 소유하며 Backend 는 이 원문을 알지 않는다."""

from __future__ import annotations

import json

from brokerage_ai.core.types import ChatMessage, MessageRole
from brokerage_ai.f3.judgment_contracts import (
    BrokerageJudgmentRequest,
    JudgmentCard,
)
from brokerage_ai.f3.judgment_model_output import EvidenceCatalogEntry, build_evidence_catalog

# v2: `each_candidate_appears_once` 가 강제하던 "같은 후보를 두 번 판정하지 않는다"를 규칙 2에
# 명시했다. JSON schema 로 표현할 수 없어 모델이 그 존재를 알 방법이 없었다.
BROKERAGE_JUDGMENT_PROMPT_VERSION = "brokerage-judgment-prompt:v5"

_ROLE = (
    "너는 중개 판정자다. 한쪽을 대리하지 않는다. 앵커 포지션 카드 1장과 반대편 후보 카드 "
    "여러 장을 한꺼번에 놓고, 어느 후보를 어떤 순서로 먼저 보여줄지와 그 이유를 정한다."
)

_RULES = (
    """규칙을 모두 지킨다.

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
6. comparison_reason 은 "왜 이 후보를 먼저 보여주는가"에 가장 가까운 code 하나다.
   comparison_detail 은 code만으로 부족한 후보별 차이만 120자 이내로 쓴다.
7. obstacle_reason 은 결정적인 장애물 하나의 code다. 없으면 NONE이다. obstacle_detail 에
   여러 장애물을 나열하지 않고 code만으로 부족한 차이만 120자 이내로 쓴다.
8. concession_reason 은 양측 카드의 flexible 에 근거한 code다. 양보 지점이 없으면 NONE이다.
   concession_detail 은 누가·무엇을·얼마나 움직이는지 필요한 경우만 120자 이내로 쓴다.
9. recommended_action 의 channel 은 대상 카드의 contactability 판정을 따른다. 연락이
   어렵다고 적힌 상대에게 통화를 먼저 제안하지 않는다.
10. 모든 후보는 evidence_refs 에 근거 reference를 1~3개 고른다.
    - reference는 입력 evidence_catalog의 ref_id만 쓴다. quote_text나 note를 다시 출력하지
      않는다.
    - 앵커 카드 또는 지금 판정하는 후보 카드의 reference만 쓴다. 다른 후보 카드의 reference를
      섞지 않는다.
11. 날짜 산수를 하지 않는다. 카드에 이미 계산된 시점 정보만 쓴다.
12. 개인정보를 생성하거나 복원하지 않는다. 가려진 이름·연락처가 무엇인지 추측하지 않고
    성명, 전화번호, 이메일, 생년월일을 출력에 넣지 않는다.
13. 법률 판단이나 공식 가격 감정으로 표현하지 않는다. 두 포지션을 놓고 본 중개 판단이다.
14. 발송 문안을 만들지 않는다. message 는 무슨 말을 꺼낼지에 대한 120자 이내 한 문장이다.
15. REJECTED이면 rejection_reason code를 반드시 쓰고, 아니면 null이다. rejection_detail은
    code만으로 부족한 후보별 차이만 120자 이내로 쓴다."""
    ""
)


def _evidence_key(value: dict[str, object]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _replace_evidence_with_refs(
    value: object, card_id: int, references: dict[tuple[int, str], int]
) -> object:
    """카드 안에서 반복되는 근거 원문을 짧은 catalog reference로 바꾼다."""
    if isinstance(value, dict):
        if value.get("kind") in {"QUOTE", "INFERENCE"}:
            return {"evidence_ref": references[(card_id, _evidence_key(value))]}
        return {
            key: _replace_evidence_with_refs(child, card_id, references)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [_replace_evidence_with_refs(child, card_id, references) for child in value]
    return value


def _card_payload(card: JudgmentCard, references: dict[tuple[int, str], int]) -> dict[str, object]:
    """카드 하나를 근거 중복 없이 프롬프트에 실을 형태로."""
    analysis = card.analysis.model_dump(mode="json")
    return {
        "card_id": card.card_id,
        "negotiation_side": card.negotiation_side.value,
        "target_label": card.target_label,
        "analysis": _replace_evidence_with_refs(analysis, card.card_id, references),
    }


def _catalog_payload(entry: EvidenceCatalogEntry) -> dict[str, object]:
    return {
        "ref_id": entry.ref_id,
        "card_id": entry.card_id,
        "evidence_side": entry.evidence_side.value,
        "field_name": entry.field_name,
        "source": entry.source.model_dump(mode="json"),
    }


def build_brokerage_judgment_messages(
    request: BrokerageJudgmentRequest,
) -> tuple[ChatMessage, ...]:
    """판정 프롬프트를 만든다. 앵커 카드는 **한 번만** 싣는다 (F3-BR-02).

    후보 수만큼 앵커를 반복하면 토큰이 낭비되고 같은 카드를 여러 번 읽은 모델의 판정이
    흔들린다.
    """
    catalog = build_evidence_catalog(request)
    references = {
        (entry.card_id, _evidence_key(entry.source.model_dump(mode="json"))): entry.ref_id
        for entry in catalog
    }
    anchor = json.dumps(
        _card_payload(request.anchor, references), ensure_ascii=False, separators=(",", ":")
    )
    candidates = json.dumps(
        [_card_payload(card, references) for card in request.candidates],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    evidence_catalog = json.dumps(
        [_catalog_payload(entry) for entry in catalog],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    body = (
        f"## 앵커 포지션 카드 1장\n\n```json\n{anchor}\n```\n\n"
        f"## 반대편 후보 포지션 카드 {len(request.candidates)}장\n\n"
        f"```json\n{candidates}\n```\n\n"
        f"## 근거 catalog\n\n```json\n{evidence_catalog}\n```"
    )
    return (
        ChatMessage(role=MessageRole.SYSTEM, content=f"{_ROLE}\n\n{_RULES}"),
        ChatMessage(role=MessageRole.USER, content=body),
    )
