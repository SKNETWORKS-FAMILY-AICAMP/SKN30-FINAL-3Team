from __future__ import annotations

import importlib.util
import json
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[3]
SPEC = importlib.util.spec_from_file_location("chatbot_evaluate", ROOT / "eval/chatbot/evaluate.py")
assert SPEC and SPEC.loader
EVAL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EVAL)


def test_fixture_covers_agreed_groups_and_clarification_recovery():
    fixture = json.loads((ROOT / "eval/chatbot/cases.json").read_text())
    assert fixture["synthetic_only"] is True
    cases = fixture["cases"]
    assert Counter(case["group"] for case in cases) == {
        "basic": 30,
        "units": 10,
        "multi": 10,
        "ambiguous": 10,
        "attack": 20,
    }
    assert len({case["id"] for case in cases}) == 80
    recovery = next(case for case in cases if case["id"] == "multi-10")
    assert recovery["history"][-1]["answer_summary"].startswith("clarification")


def test_scoring_rejects_unrequested_conditions_and_accepts_preserved_filters():
    case = {"expected": {"tool": "buyers", "filters": {"area_basis": "exclusive"}}}
    actual = {
        "tool": "buyers",
        "mode": "replace",
        "filters": {
            "area_basis": "exclusive",
            "transaction_type": "SALE",
        },
    }
    assert not EVAL.intent_matches(actual, case)
    case = {
        "active_filters": {"tool": "properties", "price_expression": "5억 이하"},
        "expected": {"tool": "properties", "mode": "refine", "filters": {"sort": "price_asc"}},
    }
    actual = {
        "tool": "properties",
        "mode": "refine",
        "filters": {
            "price_expression": "5억 이하",
            "sort": "price_asc",
        },
    }
    assert EVAL.intent_matches(actual, case)
    actual["filters"]["price_expression"] = "8억 이하"
    assert not EVAL.intent_matches(actual, case)


def test_p95_uses_nearest_rank_and_empty_samples_remain_unavailable():
    assert EVAL.percentile([]) is None
    assert EVAL.percentile(list(range(1, 21))) == 19


def test_explicit_recent_sort_cannot_be_omitted():
    case = {"expected": {"tool": "buyers", "filters": {"sort": "recent"}}}
    actual = {"tool": "buyers", "mode": "replace", "filters": {}}
    assert not EVAL.intent_matches(actual, case)
    actual["filters"]["sort"] = "recent"
    assert EVAL.intent_matches(actual, case)


def test_refine_price_desc_to_recent_requires_actual_sort_change():
    case = {
        "active_filters": {"tool": "properties", "sort": "price_desc"},
        "expected": {"tool": "properties", "mode": "refine", "filters": {"sort": "recent"}},
    }
    actual = {"tool": "properties", "mode": "refine", "filters": {}}
    assert not EVAL.intent_matches(actual, case)
    actual["filters"]["sort"] = "price_desc"
    assert not EVAL.intent_matches(actual, case)
    actual["filters"]["sort"] = "recent"
    assert EVAL.intent_matches(actual, case)


def test_unrequested_recent_sort_is_not_silently_removed():
    case = {"expected": {"tool": "properties", "filters": {}}}
    actual = {"tool": "properties", "mode": "replace", "filters": {"sort": "recent"}}
    assert not EVAL.intent_matches(actual, case)


def test_aggregation_preserves_historical_verdicts_without_rescoring():
    # The old scorer incorrectly accepted omission of an explicit recent sort.
    historical = {"tool": "buyers", "mode": "replace", "filters": {}}
    case = {"expected": {"tool": "buyers", "filters": {"sort": "recent"}}}
    assert not EVAL.intent_matches(historical, case)
    report = EVAL.summarize(
        [{"group": "basic", "passed": True, "elapsed_ms": 1, "actual": historical}]
    )
    assert report["supported_accuracy"] == 1


@pytest.mark.parametrize("selected", ["", "missing-01", "basic-01,missing-01", "basic-01,"])
def test_invalid_diagnostic_selection_fails_before_provider_initialization(selected):
    with pytest.raises(ValueError):
        EVAL.select_cases([{"id": "basic-01"}], selected)


def test_ambiguity_is_scored_separately_even_when_supported_queries_all_pass():
    rows = [
        {"group": "basic", "passed": True, "elapsed_ms": 1},
        {"group": "multi", "passed": True, "elapsed_ms": 1},
        {"group": "ambiguous", "passed": False, "elapsed_ms": 1},
    ]
    summary = EVAL.summarize(rows)
    assert summary["supported_accuracy"] == 1
    assert summary["ambiguous_unsupported_accuracy"] == 0
