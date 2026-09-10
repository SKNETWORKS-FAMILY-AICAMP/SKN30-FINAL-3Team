import asyncio
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, Mock

import pytest
from brokerage_ai.chatbot import (
    ChatAction,
    ChatFilters,
    ChatInput,
    ChatIntent,
    ChatResultItem,
    ResultReference,
)

from domain.chatbot import query
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


@pytest.mark.parametrize("category", ["LISTING_RECONTACT", "CLIENT_RECONTACT"])
@pytest.mark.parametrize("mode", ["replace", "refine"])
def test_retired_agenda_scope_clarifies_before_progress_or_database(category, mode, monkeypatch):
    session = Mock()
    monkeypatch.setattr(query, "Session", session)
    active = {"tool": "agenda", "categories": [category], "date_expression": "오늘"}
    progress = AsyncMock()
    result = asyncio.run(
        query.ChatLookup(Mock(), 1, on_search=progress).execute(
            ChatIntent(
                tool="agenda",
                mode=mode,
                filters=ChatFilters(
                    date_expression="이번 주", categories=(category,) if mode == "replace" else ()
                ),
            ),
            ChatInput(question="이번 주로", as_of=date(2026, 9, 8), active_filters=active),
        )
    )
    assert result.kind == "clarification"
    assert "재연락 기능은 지원하지 않아요" in result.text
    assert result.filters == active
    progress.assert_not_called()
    session.assert_not_called()


@pytest.mark.parametrize("offset", [0, 10])
def test_saved_retired_agenda_page_clarifies_before_database(offset, monkeypatch):
    session = Mock()
    monkeypatch.setattr(query, "Session", session)
    result = query.ChatLookup(Mock(), 1).search(
        {
            "tool": "agenda",
            "categories": ["LISTING_REVALIDATION", "LISTING_RECONTACT"],
            "start_date": "2026-09-01",
            "end_date": "2026-09-30",
        },
        offset,
    )
    assert result.kind == "clarification"
    assert "재연락 기능은 지원하지 않아요" in result.text
    session.assert_not_called()


@pytest.mark.parametrize("category", ["LISTING_RECONTACT", "CLIENT_RECONTACT"])
def test_saved_retired_agenda_reference_cannot_open_detail(category, monkeypatch):
    session = Mock()
    monkeypatch.setattr(query, "Session", session)
    reference = ResultReference(
        kind="agenda",
        items=(
            ChatResultItem(
                id=f"{category}:1:None:None:None",
                title="과거 재연락",
                action=ChatAction(type="open_property", target_id=1, label="상세 보기"),
            ),
        ),
    )
    result = asyncio.run(
        query.ChatLookup(Mock(), 1).execute(
            ChatIntent(tool="open_result", reference_ordinal=1),
            ChatInput(question="첫 번째 열기", as_of=date(2026, 9, 8), reference=reference),
        )
    )
    assert result.kind == "clarification"
    assert "재연락 기능은 지원하지 않아요" in result.text
    assert not result.actions
    session.assert_not_called()


def test_supported_refinement_replaces_retired_scope():
    filters = normalize(
        ChatIntent(
            tool="agenda", mode="refine", filters=ChatFilters(categories=("LISTING_REVALIDATION",))
        ),
        ChatInput(
            question="매물 재확인 일정으로",
            as_of=date(2026, 9, 8),
            active_filters={
                "tool": "agenda",
                "categories": ["CLIENT_RECONTACT"],
                "date_expression": "오늘",
            },
        ),
    )
    assert filters["categories"] == ["LISTING_REVALIDATION"]
    assert filters["start_date"] == filters["end_date"] == "2026-09-08"
    session = Mock()
    session.execute.return_value.scalar_one.return_value = 0
    session.execute.return_value.mappings.return_value = []
    result = query.ChatLookup(Mock(), 1)._agenda(session, filters, 0)
    assert result.kind == "agenda" and result.total == 0
    assert session.execute.call_count == 2
