from datetime import date
from decimal import Decimal

import pytest
from brokerage_ai.chatbot import ChatFilters, ChatInput, ChatIntent

from domain.chatbot.normalization import ClarificationNeeded, parse_bounds, parse_dates
from domain.chatbot.query import normalize


@pytest.mark.parametrize(
    ("source", "minimum", "maximum"),
    [
        ("5억 이하", None, "500000000"),
        ("3억 5천만원", "350000000", "350000000"),
        ("1,200만원 이상", "12000000", None),
        ("3~5억", "300000000", "500000000"),
        ("100만원 미만", None, "1000000"),
        ("5억까지", None, "500000000"),
    ],
)
def test_money_units(source, minimum, maximum):
    bounds = parse_bounds(source)
    assert bounds.minimum == (Decimal(minimum) if minimum else None)
    assert bounds.maximum == (Decimal(maximum) if maximum else None)


def test_strict_bound_and_area_conversion():
    assert not parse_bounds("3억 초과").minimum_inclusive
    assert not parse_bounds("3억 미만").maximum_inclusive
    assert parse_bounds("30평 이상", area=True).minimum == Decimal("99.173550")
    assert parse_bounds("1억 이상 3억 미만").maximum == Decimal("300000000")
    assert not parse_bounds("1억 이상 3억 미만").maximum_inclusive


@pytest.mark.parametrize("source", ["DROP TABLE", "-1억", "무제한", "5억~3억", "NaN원"])
def test_unsafe_or_ambiguous_number_never_becomes_query(source):
    with pytest.raises(ClarificationNeeded):
        parse_bounds(source)


@pytest.mark.parametrize(
    ("source", "start", "end"),
    [
        ("오늘", "2026-09-08", "2026-09-08"),
        ("이번 주", "2026-09-07", "2026-09-13"),
        ("이번 달", "2026-09-01", "2026-09-30"),
        ("다음달", "2026-10-01", "2026-10-31"),
        ("2026-09-01~2026-09-30", "2026-09-01", "2026-09-30"),
    ],
)
def test_calendar_period(source, start, end):
    assert parse_dates(source, date(2026, 9, 8)) == (
        date.fromisoformat(start),
        date.fromisoformat(end),
    )


def test_refinement_preserves_scope_and_renormalizes():
    request = ChatInput(
        question="3억 이하로",
        as_of=date(2026, 9, 8),
        active_filters={
            "tool": "properties",
            "transaction_type": "SALE",
            "price_expression": "5억 이하",
            "complex_name": "합성단지",
            "price_bounds": {"minimum": None, "maximum": "500000000"},
        },
    )
    normalized = normalize(
        ChatIntent(
            tool="properties", mode="refine", filters=ChatFilters(price_expression="3억 이하")
        ),
        request,
    )
    assert normalized["complex_name"] == "합성단지"
    assert normalized["price_bounds"]["maximum"] == "300000000"


def test_ambiguous_area_and_missing_context_require_clarification():
    request = ChatInput(question="30평", as_of=date(2026, 9, 8))
    with pytest.raises(ClarificationNeeded):
        normalize(
            ChatIntent(tool="properties", filters=ChatFilters(area_expression="30평")), request
        )
    with pytest.raises(ClarificationNeeded):
        normalize(ChatIntent(tool="properties", mode="refine"), request)
