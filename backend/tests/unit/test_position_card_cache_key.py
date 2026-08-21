from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from domain.agent_execution.cache_key import CACHE_KEY_SCHEMA_VERSION, position_card_cache_key

BASE = {
    "brokerage_id": 1,
    "negotiation_side": "LISTING",
    "anchor_type": "LISTING",
    "anchor_id": 10,
    "data_version": 3,
    "interaction_count": 2,
    "last_interaction_at": datetime(2026, 8, 19, 2, 0, tzinfo=UTC),
    "max_interaction_id": 77,
    "agent_type": "BROKERAGE_WORKFLOW",
    "model_config_id": None,
    "prompt_version": None,
    "workflow_version": None,
    "input_fingerprint": "position-card-input:v1:aaaa",
    "scope_identity": "interaction-scope:v2:bbbb",
}


def key(**overrides: object) -> str:
    return position_card_cache_key(**{**BASE, **overrides})  # pyright: ignore[reportArgumentType]


def test_same_input_gives_the_same_key() -> None:
    assert key() == key()
    assert key().startswith(f"{CACHE_KEY_SCHEMA_VERSION}:")


@pytest.mark.parametrize(
    "overrides",
    [
        {"input_fingerprint": "position-card-input:v1:cccc"},
        {"scope_identity": "interaction-scope:v2:dddd"},
        {"anchor_id": 11},
        {"data_version": 4},
        {"interaction_count": 3},
        {"max_interaction_id": 78},
        {"max_interaction_id": None},
        {"last_interaction_at": datetime(2026, 8, 19, 2, 0, 1, tzinfo=UTC)},
        {"last_interaction_at": None},
        {"negotiation_side": "REQUIREMENT"},
        {"anchor_type": "REQUIREMENT"},
        {"brokerage_id": 2},
        {"agent_type": "OTHER_WORKFLOW"},
        {"model_config_id": 5},
        {"prompt_version": "p1"},
        {"workflow_version": "w1"},
    ],
    ids=lambda value: ",".join(value),
)
def test_any_input_change_changes_the_key(overrides: dict) -> None:
    assert key(**overrides) != key()


def test_null_versions_are_deterministic() -> None:
    assert key(model_config_id=None, prompt_version=None, workflow_version=None) == key()


def test_same_instant_in_another_timezone_gives_the_same_key() -> None:
    seoul = datetime(2026, 8, 19, 11, 0, tzinfo=timezone(timedelta(hours=9)))
    assert seoul == BASE["last_interaction_at"]

    assert key(last_interaction_at=seoul) == key()


def test_empty_string_version_differs_from_null() -> None:
    assert key(prompt_version="") != key()


def test_naive_last_interaction_at_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        key(last_interaction_at=datetime(2026, 8, 19, 2, 0))


def test_missing_last_interaction_at_is_accepted() -> None:
    assert key(last_interaction_at=None, interaction_count=0, max_interaction_id=None)
