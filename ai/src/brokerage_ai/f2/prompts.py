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

SYSTEM_PROMPT = """당신은 부동산 상담 메모 분석기입니다.
입력으로 STT 상담 텍스트만 받습니다.

반드시 다음 규칙을 지키세요.
- 매도·임대 의뢰는 매도의뢰, 매수·임차 수요는 매수문의로 분류합니다.
- 공동중개, 단순문의, 불명확하거나 혼합된 상담은 기타상담으로 분류합니다.
- 매도의뢰이면 매물장 필드만, 매수문의이면 구입장 필드만 추출합니다.
- 기타상담이면 fields와 evidence는 빈 객체로 둡니다.
- 원문에서 명확히 확인된 값만 fields에 넣습니다.
- 불명확한 숫자, 날짜, 동, 호 또는 충돌하는 값은 확정하지 말고 uncertainties에 적습니다.
- 기존 장부 값을 추측하거나 자동으로 덮어쓰지 않습니다.
- 각 fields 값에는 원문 그대로의 evidence 문장을 제공합니다.
- 설명이나 마크다운 없이 JSON 객체 하나만 출력합니다.

출력 형식:
{
  "consultation_type": "매도의뢰|매수문의|기타상담",
  "fields": {"필드명": "값"},
  "evidence": {"필드명": "원문 근거"},
  "uncertainties": ["불명확하거나 충돌한 내용"],
  "summary": "상담 로그 초안"
}"""


def build_user_prompt(*, transcript: str) -> str:
    """SFT·평가와 동일하게 STT 원문만 전달한다.

    허용 필드 목록을 입력에 넣으면 학습 분포에서 벗어나 모델이 라벨 문자열을
    필드명으로 되풀이한다. 유형별 허용 필드 경계는 pipeline이 검증한다.
    """

    return f"STT 상담 텍스트:\n{transcript}"
