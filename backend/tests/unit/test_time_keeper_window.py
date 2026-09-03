"""일정 조회 창과 D-day 계산.

DB 없이 검증한다. 이 기능에서 실제로 틀리는 곳은 SQL이 아니라 "오늘이 언제인가"와
"경계를 포함하는가"이며, 둘 다 순수 함수로 떼어 놓았다.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from core.errors import ValidationError
from domain.time_keeper.models import (
    KST,
    MAX_OVERDUE_DAYS,
    MAX_RULE_DAYS,
    MAX_WITHIN_DAYS,
    build_window,
    days_until_due,
    recontact_contact_bounds,
    revalidation_received_bounds,
    today_in_business_timezone,
)


def test_window_includes_both_ends() -> None:
    window = build_window(date(2026, 9, 3), within_days=90, overdue_days=7)

    assert window.as_of == date(2026, 9, 3)
    assert window.earliest == date(2026, 8, 27)
    assert window.latest == date(2026, 12, 2)


def test_window_without_overdue_starts_today() -> None:
    window = build_window(date(2026, 9, 3), within_days=30, overdue_days=0)

    assert window.earliest == date(2026, 9, 3)


def test_window_carries_the_rule_periods_used_to_derive_tasks() -> None:
    """재연락과 매물 재확인은 저장된 날짜가 아니라 주기로 만든다."""
    window = build_window(date(2026, 9, 3), 90, 7, recontact_days=45, revalidation_days=14)

    assert window.recontact_days == 45
    assert window.revalidation_days == 14


def test_window_uses_documented_rule_defaults() -> None:
    window = build_window(date(2026, 9, 3), 90, 7)

    assert window.recontact_days == 30
    assert window.revalidation_days == 30


@pytest.mark.parametrize(
    ("within_days", "overdue_days"),
    [(0, 7), (MAX_WITHIN_DAYS + 1, 7), (90, -1), (90, MAX_OVERDUE_DAYS + 1)],
)
def test_window_rejects_values_outside_the_supported_range(
    within_days: int, overdue_days: int
) -> None:
    with pytest.raises(ValidationError):
        build_window(date(2026, 9, 3), within_days=within_days, overdue_days=overdue_days)


@pytest.mark.parametrize(
    ("recontact_days", "revalidation_days"),
    [(0, 30), (MAX_RULE_DAYS + 1, 30), (30, 0), (30, MAX_RULE_DAYS + 1)],
)
def test_window_rejects_rule_periods_outside_the_supported_range(
    recontact_days: int, revalidation_days: int
) -> None:
    with pytest.raises(ValidationError):
        build_window(
            date(2026, 9, 3),
            90,
            7,
            recontact_days=recontact_days,
            revalidation_days=revalidation_days,
        )


def test_days_until_due_is_zero_today_and_negative_once_passed() -> None:
    as_of = date(2026, 9, 3)

    assert days_until_due(date(2026, 9, 3), as_of) == 0
    assert days_until_due(date(2026, 9, 10), as_of) == 7
    assert days_until_due(date(2026, 9, 1), as_of) == -2


def test_today_follows_the_brokerage_timezone_not_utc() -> None:
    """한국 시각 오전 9시 이전에도 오늘이 밀리지 않아야 한다."""
    # 2026-09-03 23:30 UTC 는 서울에서 이미 다음 날 08:30 이다.
    assert today_in_business_timezone(datetime(2026, 9, 3, 23, 30, tzinfo=UTC)) == date(2026, 9, 4)
    # 서울 자정 직후는 아직 같은 날이다. UTC 로 읽으면 하루 전이 된다.
    assert today_in_business_timezone(datetime(2026, 9, 4, 0, 30, tzinfo=KST)) == date(2026, 9, 4)


def test_recontact_bounds_move_the_period_onto_the_constant_side() -> None:
    """컬럼에 연산이 붙으면 인덱스를 타지 못하므로 주기를 경계 쪽으로 옮긴다."""
    window = build_window(date(2026, 9, 3), 90, 7, recontact_days=30)

    lower, upper = recontact_contact_bounds(window)

    # 창의 시작(8/27)에 기한이 걸리려면 30일 전인 7/28에 접촉했어야 한다.
    assert lower == datetime(2026, 7, 28, 0, 0, tzinfo=KST)
    # 창의 끝(12/2)에 걸리는 마지막 날은 11/2이며, 그날 하루를 통째로 담도록 끝을 연다.
    assert upper == datetime(2026, 11, 3, 0, 0, tzinfo=KST)


def test_recontact_bounds_are_half_open_so_the_last_day_is_whole() -> None:
    window = build_window(date(2026, 9, 3), 90, 7, recontact_days=30)
    _lower, upper = recontact_contact_bounds(window)

    # 마지막 날 23:59 는 들어오고 다음 날 00:00 은 빠진다.
    assert datetime(2026, 11, 2, 23, 59, tzinfo=KST) < upper
    assert datetime(2026, 11, 3, 0, 0, tzinfo=KST) >= upper


def test_revalidation_bounds_shift_the_received_date_range() -> None:
    window = build_window(date(2026, 9, 3), 90, 7, revalidation_days=30)

    earliest, latest = revalidation_received_bounds(window)

    assert earliest == date(2026, 7, 28)
    assert latest == date(2026, 11, 2)
