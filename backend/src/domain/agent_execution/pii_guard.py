"""모델이 만든 자유 문자열에 개인정보가 있는지 확인한다.

프롬프트에 "개인정보를 쓰지 말라"고 적는 것은 지시일 뿐 보장이 아니다. 저장 직전에 실제
문자열을 직접 훑는다.

발견하면 **조용히 마스킹하고 성공 처리하지 않는다.** 가려서 넣으면 모델이 개인정보를 만들고
있다는 사실이 아무 데도 남지 않는다. 저장 전체를 거절해 사람이 볼 수 있게 만든다.

오류 메시지에는 발견된 값을 넣지 않는다. 오류가 곧 유출 경로가 되면 막은 의미가 없다.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator

from brokerage_ai.f3 import (
    CandidateJudgment,
    Evidence,
    PositionCardAnalysis,
)

# 마스킹과 같은 형태를 찾는다. 여기서는 자리를 세는 게 아니라 존재만 본다.
_FORBIDDEN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", re.compile(r"[0-9A-Za-z._%+\-]+@[0-9A-Za-z.\-]+\.[A-Za-z]{2,}")),
    ("resident registration number", re.compile(r"\d{6}\s?-\s?\d{7}")),
    ("phone number", re.compile(r"\d{2,3}\s?-\s?\d{3,4}\s?-\s?\d{4}|01\d{9}")),
    ("birth date", re.compile(r"\d{4}\s?[-./]\s?\d{1,2}\s?[-./]\s?\d{1,2}")),
)

# 이보다 짧은 식별값은 일반 단어와 우연히 겹칠 수 있어 그대로 비교하지 않는다.
_MINIMUM_SECRET_LENGTH = 2


class ModelOutputPrivacyError(RuntimeError):
    """모델 출력에 개인정보가 있다. 이 결과로 카드를 저장하면 안 된다."""


def _analysis_strings(analysis: PositionCardAnalysis) -> Iterator[tuple[str, str]]:
    """모델이 만든 자유 문자열만 훑는다.

    구조화 필드(금액, 날짜, 어휘 enum)는 대상이 아니다. `2026-11-30` 같은 정상 날짜를
    생년월일 패턴으로 오인해 정상 카드를 막으면 안 된다.
    """

    def from_evidence(field: str, evidence: Iterable[Evidence]) -> Iterator[tuple[str, str]]:
        for index, item in enumerate(evidence):
            if item.quote_text is not None:
                yield f"{field}.evidence.{index}.quote_text", item.quote_text
            if item.note is not None:
                yield f"{field}.evidence.{index}.note", item.note

    yield from from_evidence("intent", analysis.intent.evidence)
    yield from from_evidence("urgency", analysis.urgency.evidence)
    yield from from_evidence("contactability", analysis.contactability.evidence)
    if analysis.contactability.note is not None:
        yield "contactability.note", analysis.contactability.note
    for assessment in analysis.price:
        yield from from_evidence(f"price.{assessment.price_kind.value}", assessment.basis)
    for label, conditions in (
        ("timing.constraints", analysis.timing.constraints),
        ("flexible", analysis.flexible),
        ("inflexible", analysis.inflexible),
    ):
        for index, condition in enumerate(conditions):
            yield f"{label}.{index}.description", condition.description
            yield from from_evidence(f"{label}.{index}", condition.evidence)


def _assert_clean(fields: Iterable[tuple[str, str]], secrets: Iterable[str]) -> None:
    """자유 문자열 묶음을 훑는다. 금지 패턴이나 알려진 식별값이 있으면 거절한다."""
    known = {
        secret.strip()
        for secret in secrets
        if secret and len(secret.strip()) >= _MINIMUM_SECRET_LENGTH
    }

    for field, value in fields:
        for label, pattern in _FORBIDDEN_PATTERNS:
            if pattern.search(value):
                # 찾은 값 자체는 메시지에 넣지 않는다. 위치와 종류만 알린다.
                raise ModelOutputPrivacyError(f"model output field {field} contains a {label}")
        for secret in known:
            if secret in value:
                raise ModelOutputPrivacyError(
                    f"model output field {field} repeats a known personal identifier"
                )


def assert_no_personal_data(analysis: PositionCardAnalysis, secrets: Iterable[str]) -> None:
    """모델 자유 문자열에 금지 패턴이나 알려진 식별값이 있으면 거절한다.

    `secrets`는 요청을 조립할 때 가린 값들이다. 마스킹된 본문만 봤는데도 원문 이름이나
    연락처가 결과에 다시 나타났다면 모델이 그것을 만들어 낸 것이므로 저장하지 않는다.
    """
    _assert_clean(_analysis_strings(analysis), secrets)


def _judgment_strings(
    candidates: Iterable[CandidateJudgment],
) -> Iterator[tuple[str, str]]:
    """중개 판정에서 모델이 **새로 만든** 자유 문자열만 훑는다."""
    for candidate in candidates:
        prefix = f"candidate.{candidate.card_id}"
        yield f"{prefix}.comparison_basis", candidate.comparison_basis
        for name in ("primary_obstacle", "possible_concession", "rejection_reason"):
            value = getattr(candidate, name)
            if value is not None:
                yield f"{prefix}.{name}", value
        if candidate.recommended_action is not None:
            yield f"{prefix}.recommended_action.message", candidate.recommended_action.message
        for index, item in enumerate(candidate.evidence):
            if item.source.note is not None:
                yield f"{prefix}.evidence.{index}.note", item.source.note


def assert_no_personal_data_in_judgment(candidates: Iterable[CandidateJudgment]) -> None:
    """중개 판정 자유 문자열에 개인정보 패턴이 있으면 거절한다.

    포지션 카드와 달리 `secrets` 를 받지 않는다. 판정 모델은 이미 마스킹과 개인정보 검사를
    통과한 카드만 보고, 인용은 그 카드가 이미 갖고 있던 인용과 글자 그대로 같아야만 통과한다
    (`validate_judgment_result`). 따라서 인용으로는 새 개인정보가 들어올 수 없고, 새로 생기는
    자유 문자열은 위 목록뿐이라 패턴 검사로 충분하다.

    가려야 할 값 목록을 여기서 다시 만들려면 앵커와 후보 전부의 로그 범위를 재조립해야 하는데,
    그 비용에 비해 얻는 것이 없다.
    """
    _assert_clean(_judgment_strings(candidates), ())


def assert_no_personal_data_in_text(field: str, value: str) -> None:
    """사용자가 직접 쓴 자유문에 개인정보 패턴이 있으면 거절한다.

    모델 출력과 같은 패턴 목록을 쓴다. 사용자가 쓴 글이라도 성명·연락처를 AI 판정 기록에
    남기면 그 기록의 개인정보 경계가 무너진다. 무엇을 발견했는지는 메시지에 넣지 않는다.
    """
    _assert_clean(((field, value),), ())
