from __future__ import annotations

from brokerage_ai.f2.types import LedgerType

PROPERTY_FIELDS = frozenset(
    {
        "단지",
        "평형",
        "동",
        "호",
        "타입",
        "방향",
        "현상태",
        "현재 보증금",
        "현재 차임",
        "융자",
        "만기일",
        "접수일",
        "현매물",
        "진행상태",
        "명도 조건",
        "매매가",
        "전세보증금",
        "월세 보증금",
        "월세 차임",
        "확장 여부",
        "붙박이",
        "시설 상태",
        "임대인",
        "임대인 전화",
        "임차인",
        "임차인 전화",
        "관련 중개업소",
        "담당자",
        "비고",
    }
)

BUYER_FIELDS = frozenset(
    {
        "접수일",
        "최종접촉일",
        "거래 구분",
        "희망 단지",
        "희망 지역",
        "희망 평형",
        "금액 원문",
        "이사일 원문",
        "구입자 이름",
        "구입자 별칭",
        "전화번호",
        "관련 중개업소",
        "진행단계",
        "완료 여부",
        "담당자",
        "분류",
        "비고",
    }
)

ALLOWED_FIELDS = {
    LedgerType.PROPERTY: PROPERTY_FIELDS,
    LedgerType.BUYER: BUYER_FIELDS,
}

SYSTEM_PROMPT = """당신은 부동산 상담 음성메모의 텍스트를 분석하는 도구입니다.
반드시 지정된 JSON 스키마만 출력하고 다음 규칙을 지키세요.

- 상담 유형은 매도의뢰, 매수문의, 공동중개, 단순문의 중 하나입니다.
- 매물장+매수문의 또는 구입장+매도의뢰이면 ledger_mismatch를 true로 둡니다.
- 장부 불일치, 공동중개, 단순문의일 때 fields와 evidence는 빈 객체로 둡니다.
- 현재 장부에 허용된 필드만 사용합니다.
- 원문에서 명확히 확인되는 값을 원문 표현 그대로 추출합니다.
- 음성에 없는 값은 추측하지 않습니다.
- 불명확한 숫자·날짜·동·호와 충돌하는 값은 fields에 넣지 않고 uncertainties에 적습니다.
- fields의 모든 항목에 STT 원문 안에 실제로 존재하는 evidence 문장을 제공합니다.
- 개인정보 동의 여부는 사용자가 직접 확인하는 값이므로 fields에 제안하지 않습니다.
- summary에는 핵심 내용, 확정 조건, 추가 확인 사항을 포함한 상담 로그 초안을 작성합니다.
"""


def build_user_prompt(*, transcript: str, ledger_type: LedgerType) -> str:
    """정답이나 기존 장부값을 노출하지 않고 모델에 필요한 최소 입력만 만든다."""

    allowed_fields = ", ".join(sorted(ALLOWED_FIELDS[ledger_type]))
    return (
        f"현재 장부 종류: {ledger_type.value}\n"
        f"허용 필드: {allowed_fields}\n"
        f"STT 상담 텍스트:\n{transcript}"
    )
