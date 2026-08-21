"""AI 입력 마스킹 검증.

가장 중요한 성질은 **길이 보존**이다. AI 는 마스킹된 본문에서 인용을 돌려주고 Backend 는
그 위치를 원본 상담 로그의 위치로 그대로 쓴다. 길이가 한 글자라도 달라지면 근거가 원문의
엉뚱한 자리를 가리킨다.
"""

from __future__ import annotations

import pytest

from domain.agent_execution.masking import mask_text


def test_a_korean_name_is_replaced_by_the_same_number_of_characters() -> None:
    masked = mask_text("김철수 사장님과 통화했다", ["김철수"])

    assert masked == "*** 사장님과 통화했다"


def test_an_alternate_name_is_masked_too() -> None:
    masked = mask_text("등기부에는 김영희, 통칭 영희씨로 적혀 있다", ["김영희", "영희씨"])

    assert masked is not None
    assert "김영희" not in masked
    assert "영희씨" not in masked


@pytest.mark.parametrize(
    ("text", "hidden"),
    [
        ("연락처는 010-1234-5678 입니다", "010-1234-5678"),
        ("전화 01012345678 로 주세요", "01012345678"),
        ("사무실 02-555-1234", "02-555-1234"),
    ],
    ids=["휴대폰", "구분기호_없음", "유선"],
)
def test_phone_numbers_are_masked_without_a_known_value(text: str, hidden: str) -> None:
    """대응표에 없어도 패턴만으로 잡아야 한다. 원문에 남으면 그대로 AI 로 나간다."""
    masked = mask_text(text, [])

    assert masked is not None
    assert hidden not in masked
    assert len(masked) == len(text)


def test_an_email_is_masked_but_keeps_its_shape() -> None:
    masked = mask_text("메일은 buyer.kim@example.com 으로", [])

    # 구분 기호는 자리를 지키고 값만 가린다.
    assert masked == "메일은 *****.***@*******.*** 으로"


@pytest.mark.parametrize(
    "text",
    ["생년월일 1978-04-11", "생일 1978.04.11", "주민 780411-1234567"],
    ids=["하이픈", "점", "주민번호"],
)
def test_birth_dates_and_resident_numbers_are_masked(text: str) -> None:
    masked = mask_text(text, [])

    assert masked is not None
    assert not any(character.isdigit() for character in masked)
    assert len(masked) == len(text)


def test_login_id_and_display_name_are_masked() -> None:
    masked = mask_text("담당자 kim.agent(김중개)가 처리", ["kim.agent", "김중개"])

    assert masked is not None
    assert "kim.agent" not in masked
    assert "김중개" not in masked


def test_the_longest_known_value_wins_when_values_overlap() -> None:
    """짧은 값을 먼저 지우면 긴 값의 나머지가 남는다."""
    masked = mask_text("김철수 사장", ["김철", "김철수"])

    assert masked == "*** 사장"


def test_masking_preserves_length_for_every_kind_of_value() -> None:
    text = "김철수(010-1234-5678, kim@example.com, 1978-04-11) 상담"

    masked = mask_text(text, ["김철수"])

    assert masked is not None
    assert len(masked) == len(text)
    for secret in ("김철수", "010-1234-5678", "kim@example.com", "1978-04-11"):
        assert secret not in masked


def test_masking_is_deterministic() -> None:
    text = "김철수 010-1234-5678"

    assert mask_text(text, ["김철수"]) == mask_text(text, ["김철수"])


def test_the_result_carries_neither_the_original_nor_a_lookup_table() -> None:
    """대응표를 만들지 않는다. 되돌릴 수 있으면 저장 금지 대상이 하나 더 생긴다."""
    masked = mask_text("김철수 010-1234-5678", ["김철수"])

    assert masked == "*** ***-****-****"
    assert isinstance(masked, str)


def test_blank_and_missing_values_pass_through() -> None:
    assert mask_text(None, ["김철수"]) is None
    assert mask_text("메모 없음", []) == "메모 없음"
    assert mask_text("공백만 있는 secret", ["", "   "]) == "공백만 있는 secret"


def test_raw_text_fields_use_the_same_function() -> None:
    """상담 로그와 `*_raw_text` 가 다른 규칙을 쓰면 한쪽으로 개인정보가 샌다."""
    budget_raw = "김철수 사장님 예산 28.5억, 010-1234-5678 로 확인"

    masked = mask_text(budget_raw, ["김철수"])

    assert masked is not None
    assert "김철수" not in masked
    assert "010-1234-5678" not in masked
    assert "28.5억" in masked
    assert len(masked) == len(budget_raw)
