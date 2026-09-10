"""Current Time Keeper capabilities remain safe for historical chatbot filters."""

import asyncio
from datetime import date
from unittest.mock import AsyncMock, Mock

import pytest
from brokerage_ai.chatbot import ChatFilters, ChatInput, ChatIntent

from domain.chatbot import query


@pytest.mark.parametrize("category", ["LISTING_RECONTACT", "CLIENT_RECONTACT"])
@pytest.mark.parametrize("mode", ["replace", "refine"])
def test_retired_recontact_requests_clarification_before_lookup(category, mode, monkeypatch):
    session = Mock()
    monkeypatch.setattr(query, "Session", session)
    active = {"tool": "agenda", "categories": [category], "date_expression": "오늘"}
    request = ChatInput(
        question="이번 주로 조회해줘", as_of=date(2026, 9, 8), active_filters=active
    )
    filters = ChatFilters(
        date_expression="이번 주", categories=(category,) if mode == "replace" else ()
    )
    progress = AsyncMock()
    result = asyncio.run(
        query.ChatLookup(Mock(), 1, on_search=progress).execute(
            ChatIntent(tool="agenda", mode=mode, filters=filters), request
        )
    )
    assert result.kind == "clarification"
    assert "재연락 기능은 지원하지 않아요" in result.text
    assert result.filters == active
    assert result.items == ()
    progress.assert_not_called()
    session.assert_not_called()


@pytest.mark.parametrize("offset", [0, 10])
def test_historical_recontact_result_page_is_not_reported_as_empty(offset, monkeypatch):
    session = Mock()
    monkeypatch.setattr(query, "Session", session)
    filters = {
        "tool": "agenda",
        "categories": ["LISTING_REVALIDATION", "LISTING_RECONTACT"],
        "start_date": "2026-09-01",
        "end_date": "2026-09-30",
    }
    result = query.ChatLookup(Mock(), 1).search(filters, offset)
    assert result.kind == "clarification"
    assert "재연락 기능은 지원하지 않아요" in result.text
    session.assert_not_called()


def test_replacing_retired_scope_with_supported_category_restores_search():
    filters = query.normalize(
        ChatIntent(
            tool="agenda",
            mode="refine",
            filters=ChatFilters(categories=("LISTING_REVALIDATION",)),
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
    assert filters["start_date"] == "2026-09-08"
    session = Mock()
    session.execute.return_value.scalar_one.return_value = 0
    session.execute.return_value.mappings.return_value = []
    # Construct the actual Time Keeper union and its window (no DB needed).
    result = query.ChatLookup(Mock(), 1)._agenda(session, filters, 0)
    assert result.kind == "agenda"
    assert result.total == 0
    assert session.execute.call_count == 2
