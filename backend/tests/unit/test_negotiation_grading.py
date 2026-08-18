"""등급 산출 유닛 테스트.

기대값은 `06_프로토타입_F3플로우/grading.py` 를 같은 입력으로 돌려 뽑은 것이다. 이 포트가
프로토타입과 다른 등급을 내면 13케이스 대조에서 원인이 카드인지 규칙인지 갈라볼 수 없다.

이 파일 전체가 **모델 호출 없이** 돈다 (수용 기준 1 · F3-NF-08).
"""

from __future__ import annotations

from datetime import date

import pytest

from domain.negotiation.grading import AnchorFacts, CandidateFacts, grade

DEADLINE = date(2027, 3, 2)
HANDOVER = date(2026, 12, 15)


def anchor(**overrides: object) -> AnchorFacts:
    values: dict[str, object] = {
        "deal_type": "매매",
        "budget_est": 23.5,
        "deadline": DEADLINE,
        "intent": "있음",
        "contact": "양호",
    }
    values.update(overrides)
    return AnchorFacts(**values)  # pyright: ignore[reportArgumentType]


def candidate(**overrides: object) -> CandidateFacts:
    values: dict[str, object] = {
        "id": "1",
        "deal_type": "매매",
        "price_est": 23.3,
        "concession": 0.0,
        "available_from": HANDOVER,
        "intent": "있음",
        "contact": "양호",
        "cond_total": 3,
        "cond_met": 1,
        "cond_unknown": 2,
    }
    values.update(overrides)
    return CandidateFacts(**values)  # pyright: ignore[reportArgumentType]


def test_matching_pair_scores_strong() -> None:
    result = grade(anchor(), candidate())

    assert result.grade == "강함"
    assert result.score == 97.0
    assert result.axes["price"].note == "이격 -0.9% (후보 23.3 / 상한 23.5)"
    assert result.axes["timing"].note == "여유 77일"
    assert result.axes["cond"].note == "1/1 충족, 2건 불명"


def test_price_beyond_the_gate_is_rejected() -> None:
    """G5 — 상한 15% 를 넘으면 점수를 매기지 않고 기각한다."""
    result = grade(
        anchor(budget_est=22.0),
        candidate(price_est=26.4, cond_total=1, cond_met=1, cond_unknown=0),
    )

    assert result.grade == "기각"
    assert result.score is None
    assert result.hard == ("G5 가격 이격 +20.0% — 상한 15% 초과",)


def test_handover_after_the_deadline_is_rejected() -> None:
    result = grade(
        anchor(budget_est=24.0, deadline=date(2026, 11, 30)),
        candidate(price_est=23.4, cond_total=1, cond_met=1, cond_unknown=0),
    )

    assert result.grade == "기각"
    assert result.hard == (
        "G4 시점 충돌 — 인도 2026-12-15 > 마감 2026-11-30 (15일 초과)",
    )


def test_deal_type_mismatch_cites_the_card_reference() -> None:
    """G1 — 장부 표기가 아니라 카드의 `deal_type_now` 로 건다."""
    result = grade(
        anchor(budget_est=23.0, deadline=None),
        candidate(
            price_est=23.0,
            deal_type="임대",
            deal_type_ref="[26-07 주]월세로 돌린다",
            cond_total=1,
            cond_met=1,
            cond_unknown=0,
        ),
    )

    assert result.grade == "기각"
    assert result.hard == (
        "G1 거래 유형 불일치 — 앵커 매매 / 후보 임대 · [26-07 주]월세로 돌린다",
    )


def test_withdrawn_intent_is_attributed_to_the_side_that_said_it() -> None:
    rejected_by_candidate = grade(
        anchor(), candidate(intent="철회", intent_ref="[26-05 주]①안 판다")
    )
    rejected_by_anchor = grade(anchor(intent="철회"), candidate())

    assert rejected_by_candidate.hard == ("G2 후보 의향 철회 — [26-05 주]①안 판다",)
    assert rejected_by_anchor.hard == ("G2 앵커 의향 철회",)


def test_hold_flag_demotes_one_step_without_changing_the_score() -> None:
    """보류 게이트는 기각이 아니라 강등이다 — 확인하면 되살아난다."""
    result = grade(anchor(), candidate(hold=("공동명의 — 단독 결정 불가",)))

    assert result.grade == "중간"
    assert result.score == 97.0
    assert result.flags == ("확인 필요로 1단계 강등",)


def test_missing_estimates_score_half_with_a_penalty_and_demote() -> None:
    result = grade(
        anchor(deadline=None, intent="불명", contact="주의"),
        candidate(
            price_est=None,
            available_from=None,
            intent="불명",
            contact="주의",
            cond_total=0,
            cond_met=0,
            cond_unknown=0,
        ),
    )

    assert result.grade == "약함"
    assert result.score == 35.0
    assert result.flags == ("근거 부족으로 1단계 강등",)
    assert result.axes["price"].note == "판정 불가 — 추정값 없음"


def test_concession_is_subtracted_before_the_gap_is_measured() -> None:
    result = grade(
        anchor(budget_est=22.0),
        candidate(
            price_est=23.0,
            concession=0.5,
            available_from=date(2026, 10, 1),
            contact="주의",
            cond_total=2,
            cond_met=1,
            cond_unknown=1,
        ),
    )

    assert result.grade == "강함"
    assert result.score == 86.8
    assert result.axes["price"].note == (
        "이격 +2.3% (후보 22.5 / 상한 22.0), 양보 0.5억 반영"
    )


def test_required_condition_violation_is_a_hard_gate() -> None:
    result = grade(anchor(), candidate(violates=("평형 25.0평 < 희망 33.0평",)))

    assert result.grade == "기각"
    assert result.hard == ("G3 필수 조건 위반 — 평형 25.0평 < 희망 33.0평",)


@pytest.mark.parametrize("run", range(3))
def test_same_input_always_yields_the_same_grade(run: int) -> None:
    """F3-NF-08 — 재현성. 난수도 시각 조회도 없으므로 몇 번 돌려도 같아야 한다."""
    result = grade(anchor(), candidate())

    assert (result.grade, result.score) == ("강함", 97.0)
