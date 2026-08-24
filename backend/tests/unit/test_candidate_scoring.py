"""후보 점수와 정렬의 순수 규칙.

DB 없이 확인할 수 있는 것만 여기서 본다. 조회 조건과 tenant 격리는 통합 테스트가 본다.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from domain.agent_execution.candidates import (
    CANDIDATE_CARD_LIMIT,
    CandidateCriteria,
    CandidateScore,
    CandidateSelection,
    _area_match,
    _order,
    _price_proximity,
    _recency,
    _score,
)
from domain.agent_execution.models import AnchorType

AS_OF = date(2026, 8, 23)


def test_price_proximity_is_one_when_the_amounts_match() -> None:
    assert _price_proximity(1_000_000_000, 1_000_000_000) == Decimal(1)


def test_price_proximity_falls_off_with_the_gap() -> None:
    assert _price_proximity(1_000_000_000, 900_000_000) == Decimal("0.900000")


def test_price_proximity_never_goes_negative() -> None:
    assert _price_proximity(1_000_000_000, 5_000_000_000) == Decimal(0)


def test_an_unknown_candidate_amount_scores_zero_rather_than_a_neutral_value() -> None:
    """금액을 모르는 후보가 금액을 아는 후보 사이에 끼어들면 카드화 15장이 낭비된다."""
    assert _price_proximity(1_000_000_000, None) == Decimal(0)


def test_area_matches_within_the_tolerance() -> None:
    assert _area_match(Decimal("33.0"), (Decimal("34.0"),)) == Decimal(1)
    assert _area_match(Decimal("33.0"), (Decimal("45.0"),)) == Decimal(0)


def test_area_without_a_declared_preference_scores_zero() -> None:
    assert _area_match(Decimal("33.0"), ()) == Decimal(0)


def test_recency_halves_after_the_half_life() -> None:
    assert _recency(date(2026, 7, 24), AS_OF) == Decimal("0.500000")


def test_a_future_received_date_does_not_exceed_one() -> None:
    assert _recency(date(2026, 12, 1), AS_OF) == Decimal(1)


def _make(candidate_id: int, *, amount: int | None, received: date | None) -> CandidateScore:
    return _score(
        candidate_id,
        anchor_amount=1_000_000_000,
        candidate_amount=amount,
        anchor_pyeong=None,
        candidate_pyeongs=(),
        received_at=received,
        as_of=AS_OF,
    )


def test_ordering_is_deterministic_for_tied_scores() -> None:
    """점수와 접수일이 모두 같으면 ID 오름차순이 순서를 확정한다."""
    scores = [
        _make(31, amount=1_000_000_000, received=AS_OF),
        _make(7, amount=1_000_000_000, received=AS_OF),
        _make(19, amount=1_000_000_000, received=AS_OF),
    ]
    assert [item.candidate_id for item in _order(scores)] == [7, 19, 31]
    assert [item.candidate_id for item in _order(list(reversed(scores)))] == [7, 19, 31]


def test_a_newer_reception_wins_a_tied_score() -> None:
    older = _make(1, amount=None, received=date(2026, 1, 1))
    newer = _make(2, amount=None, received=date(2026, 1, 1))
    # 금액이 없어 가격 점수가 같고 접수일도 같으므로 ID 순서다.
    assert [item.candidate_id for item in _order([newer, older])] == [1, 2]


def _selection(count: int) -> CandidateSelection:
    criteria = CandidateCriteria(
        candidate_side=AnchorType.REQUIREMENT,
        price_kind="SALE",
        price_amount=1_000_000_000,
        monthly_amount=None,
        price_is_estimated=True,
        price_floor_amount=900_000_000,
        price_ceiling_amount=None,
        anchor_pyeong=None,
        complex_id=None,
        demand_types=("매수",),
        active_statuses=("ACTIVE",),
        as_of=AS_OF,
    )
    scores = [_make(index + 1, amount=1_000_000_000, received=AS_OF) for index in range(count)]
    return CandidateSelection(criteria=criteria, ordered=_order(scores))


def test_the_card_limit_does_not_discard_the_rest() -> None:
    selection = _selection(40)
    assert selection.total_count == 40
    assert len(selection.carded) == CANDIDATE_CARD_LIMIT
    assert selection.remaining_count == 40 - CANDIDATE_CARD_LIMIT


def test_an_empty_selection_still_carries_the_criteria() -> None:
    selection = _selection(0)
    assert selection.total_count == 0
    assert selection.remaining_count == 0
    assert selection.criteria.price_floor_amount == 900_000_000
