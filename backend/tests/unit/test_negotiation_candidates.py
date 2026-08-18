"""후보 추출 유닛 테스트 — LLM 0회 (수용 기준 1).

핵심은 A-1-1 이 확인하는 것: 상한을 **장부 표기 예산**으로 잡느냐 **카드의 추정값**으로
잡느냐에 따라 후보 집합이 달라진다 (수용 기준 7).
"""

from __future__ import annotations

from domain.negotiation.candidates import (
    TOP_N,
    CandidateRow,
    anchor_cap,
    price_gate,
    select_candidates,
)

LEDGER = [
    CandidateRow(unit_id=1, label="203동 1101호", book_amount=22.3, pyeong=33.0),
    CandidateRow(unit_id=4, label="106동 2104호", book_amount=25.8, pyeong=33.0),
    CandidateRow(unit_id=8, label="105동 901호", book_amount=26.4, pyeong=33.0),
    CandidateRow(unit_id=15, label="115동 504호", book_amount=17.2, pyeong=25.0),
]


def test_gate_allows_a_margin_above_the_ceiling() -> None:
    assert price_gate(22.0) == 22.0 * 1.15


def test_estimated_price_takes_priority_over_the_recorded_budget() -> None:
    assert anchor_cap(23.5, 22.0) == 23.5
    assert anchor_cap(None, 22.0) == 22.0
    assert anchor_cap(None, None) is None


def test_recorded_budget_and_estimated_ceiling_yield_different_candidate_sets() -> None:
    """A-1-1 — 표기 22.0억이면 26.4억이 게이트 밖, 추정 23.5억이면 안이다."""
    by_book = select_candidates(LEDGER, cap=22.0, desired_pyeong=33.0)
    by_estimate = select_candidates(LEDGER, cap=23.5, desired_pyeong=33.0)

    assert 8 not in {row.unit_id for row in by_book.kept}
    assert 8 in {row.unit_id for row in by_estimate.kept}


def test_units_beyond_the_gate_are_reported_with_a_reason() -> None:
    selection = select_candidates(LEDGER, cap=22.0, desired_pyeong=33.0)

    dropped = {item.unit_id: item.reason for item in selection.dropped}
    assert dropped == {4: "가격 게이트 밖", 8: "가격 게이트 밖"}
    assert selection.total == len(LEDGER)


# 가격은 상한에 딱 맞지만 평형이 모자란 매물 하나를 섞는다.
NEAR_PRICE_SMALL = CandidateRow(unit_id=15, label="115동 504호", book_amount=20.0, pyeong=25.0)
FAR_PRICE_FIT = CandidateRow(unit_id=1, label="203동 1101호", book_amount=22.3, pyeong=33.0)


def test_meeting_the_desired_pyeong_outranks_a_closer_price() -> None:
    """평형 미달은 -5, 충족은 +2 이라 가격이 더 가까워도 뒤로 밀린다."""
    selection = select_candidates(
        [NEAR_PRICE_SMALL, FAR_PRICE_FIT], cap=20.0, desired_pyeong=33.0
    )

    assert [row.unit_id for row in selection.kept] == [1, 15]


def test_selection_is_capped_at_top_n_and_reports_the_cut() -> None:
    rows = [
        CandidateRow(unit_id=index, label=f"{index}호", book_amount=22.0, pyeong=33.0)
        for index in range(1, TOP_N + 4)
    ]

    selection = select_candidates(rows, cap=22.0, desired_pyeong=33.0)

    assert len(selection.kept) == TOP_N
    assert {item.reason for item in selection.dropped} == {f"상위 {TOP_N}건 컷"}


def test_selection_is_deterministic_for_the_same_input() -> None:
    first = select_candidates(LEDGER, cap=23.5, desired_pyeong=33.0)
    second = select_candidates(LEDGER, cap=23.5, desired_pyeong=33.0)

    assert [row.unit_id for row in first.kept] == [row.unit_id for row in second.kept]


def test_ties_break_on_unit_id_so_the_order_is_stable() -> None:
    rows = [
        CandidateRow(unit_id=9, label="9호", book_amount=22.0, pyeong=33.0),
        CandidateRow(unit_id=2, label="2호", book_amount=22.0, pyeong=33.0),
    ]

    selection = select_candidates(rows, cap=22.0, desired_pyeong=33.0)

    assert [row.unit_id for row in selection.kept] == [2, 9]


def test_no_desired_pyeong_means_no_pyeong_penalty() -> None:
    """희망 평형이 없으면 페널티가 사라져 순수 가격 근접도로 정렬된다."""
    selection = select_candidates(
        [NEAR_PRICE_SMALL, FAR_PRICE_FIT], cap=20.0, desired_pyeong=None
    )

    assert [row.unit_id for row in selection.kept] == [15, 1]
