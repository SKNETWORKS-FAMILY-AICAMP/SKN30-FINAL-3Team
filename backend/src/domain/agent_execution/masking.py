"""AI에 넘기기 전에 개인정보를 가리는 순수 함수.

**길이를 보존한다.** AI는 마스킹된 본문에서 인용을 돌려주고 Backend는 그 인용의 위치를
마스킹된 본문에서 찾는다. 길이가 같아야 그 위치가 원본 상담 로그의 같은 문자 위치가 되고,
그 덕분에 치환 대응표를 어디에도 저장하지 않아도 된다.

이 모듈은 DB와 설정을 모른다. 입력 문자열과 가려야 할 값 목록만 받는다.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

MASK_CHARACTER = "*"

# 자릿수와 구분 기호는 남기고 값만 가린다. 길이가 바뀌면 offset 대응이 깨진다.
_KEEP_IN_PATTERN = frozenset("-.@/ ()")

_PATTERNS: tuple[re.Pattern[str], ...] = (
    # 이메일. 로컬 파트와 도메인을 모두 가리되 @ 와 . 는 남긴다.
    re.compile(r"[0-9A-Za-z._%+\-]+@[0-9A-Za-z.\-]+\.[A-Za-z]{2,}"),
    # 주민등록번호 형태. 전화번호보다 먼저 잡아야 앞 6자리만 부분 매칭되지 않는다.
    re.compile(r"\d{6}\s?-\s?\d{7}"),
    # 생년월일 형태.
    re.compile(r"\d{4}\s?[-./]\s?\d{1,2}\s?[-./]\s?\d{1,2}"),
    # 전화번호. 국내 유선·휴대폰과 구분 기호 없는 표기를 함께 다룬다.
    re.compile(r"\d{2,3}\s?-\s?\d{3,4}\s?-\s?\d{4}"),
    re.compile(r"01\d{9}"),
)


def _blank_out(value: str) -> str:
    """같은 길이로 바꾼다. 구분 기호와 공백은 자리를 지킨다."""
    return "".join(
        character if character in _KEEP_IN_PATTERN or character.isspace() else MASK_CHARACTER
        for character in value
    )


def mask_text(text: str | None, secrets: Iterable[str]) -> str | None:
    """알려진 식별값과 연락처·생년월일 패턴을 같은 길이로 가린다.

    긴 값을 먼저 처리한다. 짧은 값이 긴 값의 일부일 때 짧은 쪽을 먼저 가리면 긴 값의 나머지가
    그대로 남는다. 같은 입력은 항상 같은 결과가 된다.
    """
    if text is None:
        return None

    masked = text
    known = sorted({secret.strip() for secret in secrets if secret and secret.strip()}, key=len)
    for secret in reversed(known):
        masked = masked.replace(secret, MASK_CHARACTER * len(secret))

    for pattern in _PATTERNS:
        masked = pattern.sub(lambda match: _blank_out(match.group(0)), masked)

    if len(masked) != len(text):  # pragma: no cover - 방어. 길이가 바뀌면 offset이 깨진다.
        raise ValueError("masking must preserve the original length")
    return masked
