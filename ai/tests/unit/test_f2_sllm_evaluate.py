from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest


def load_evaluate_module(monkeypatch: pytest.MonkeyPatch):
    torch = ModuleType("torch")
    yaml = ModuleType("yaml")
    transformers = ModuleType("transformers")
    vars(transformers).update(
        {
            "AutoModelForCausalLM": object,
            "AutoTokenizer": object,
            "BitsAndBytesConfig": object,
        }
    )
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "yaml", yaml)
    monkeypatch.setitem(sys.modules, "transformers", transformers)

    path = Path(__file__).parents[2] / "eval" / "f2_sLLM" / "evaluate.py"
    spec = importlib.util.spec_from_file_location("f2_sllm_evaluate_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def test_accepts_an_immutable_revision_for_one_model(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_evaluate_module(monkeypatch)

    assert module.validate_requested_model_revision("a" * 40, 1) == "a" * 40


@pytest.mark.parametrize("revision", ["main", "A" * 40, "a" * 39])
def test_rejects_a_non_commit_revision(
    monkeypatch: pytest.MonkeyPatch,
    revision: str,
) -> None:
    module = load_evaluate_module(monkeypatch)

    with pytest.raises(ValueError, match="40자리"):
        module.validate_requested_model_revision(revision, 1)


def test_rejects_one_revision_for_multiple_models(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_evaluate_module(monkeypatch)

    with pytest.raises(ValueError, match="모델 하나"):
        module.validate_requested_model_revision("a" * 40, 2)


def test_full_prompt_does_not_expose_current_ledger(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_evaluate_module(monkeypatch)

    prompt = module.build_user_prompt(
        {"transcript": "한강아파트를 사고 싶어요.", "ledger_type": "매물장"},
        "full",
    )

    assert prompt == "STT 상담 텍스트:\n한강아파트를 사고 싶어요."


def test_full_evaluation_excludes_legacy_mismatch_rows(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = load_evaluate_module(monkeypatch)
    path = tmp_path / "test.jsonl"
    rows = [
        {
            "sample_id": "matched",
            "transcript": "매수 문의",
            "ledger_type": "구입장",
            "expected": {"ledger_mismatch": False},
        },
        {
            "sample_id": "mismatch",
            "transcript": "매수 문의",
            "ledger_type": "매물장",
            "expected": {"ledger_mismatch": True},
        },
    ]
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )

    loaded = module.load_dataset(path, None, "full", ["매도의뢰", "매수문의", "기타상담"])

    assert [row["sample_id"] for row in loaded] == ["matched"]


def test_full_metrics_match_hand_calculated_extraction_table(monkeypatch: pytest.MonkeyPatch):
    module = load_evaluate_module(monkeypatch)
    rows = [
        {
            "expected": {"consultation_type": "A", "fields": {"x": "1", "y": "2"}},
            "prediction": {"consultation_type": "A", "fields": {"x": "1", "y": "wrong"}},
            "evidence_grounding_violations": 1,
            "latency_seconds": 1.0,
            "error": None,
        },
        {
            "expected": {"consultation_type": "B", "fields": {"z": "3", "w": "4"}},
            "prediction": {"consultation_type": "A", "fields": {"z": "3"}},
            "evidence_grounding_violations": 0,
            "latency_seconds": 3.0,
            "error": None,
        },
        {
            "expected": {"consultation_type": "B", "fields": {"q": "5"}},
            "prediction": None,
            "evidence_grounding_violations": 0,
            "latency_seconds": 999.0,
            "error": "synthetic parse failure",
        },
    ]

    metrics = module.calculate_metrics(rows, ["A", "B"])

    # The full evaluator intentionally reports extraction/class scores on parsed rows;
    # its separate parse rate exposes failed samples. Classification-only scores below
    # instead count invalid outputs in their denominator. Do not mix these protocols.
    assert metrics["samples"] == 3
    assert metrics["json_parse_rate"] == pytest.approx(2 / 3)
    assert metrics["classification_accuracy"] == 0.5
    assert metrics["classification_f1_by_class"] == {"A": pytest.approx(2 / 3), "B": 0.0}
    assert metrics["classification_macro_f1"] == pytest.approx(1 / 3)
    # TP=2, FP=1 (wrong y), FN=2 (correct y and missing w).
    assert metrics["field_precision"] == pytest.approx(2 / 3)
    assert metrics["field_recall"] == 0.5
    assert metrics["field_f1"] == pytest.approx(4 / 7)
    assert metrics["evidence_grounding_violations"] == 1
    assert metrics["mean_latency_seconds"] == 2.0
    assert metrics["p95_latency_seconds"] == 3.0


def test_classification_scores_include_failed_and_unknown_predictions(
    monkeypatch: pytest.MonkeyPatch,
):
    module = load_evaluate_module(monkeypatch)
    cases = [("A", "A"), ("A", "B"), ("B", "B"), ("B", None), ("A", "unknown")]
    rows = [
        {
            "expected": {"consultation_type": expected},
            "prediction": {"consultation_type": predicted} if predicted else None,
            "latency_seconds": float(index + 1),
            "error": None if predicted else "parse failure",
        }
        for index, (expected, predicted) in enumerate(cases)
    ]

    metrics = module.calculate_classification_metrics(rows, ["A", "B"])

    assert metrics["json_parse_rate"] == 0.8
    assert metrics["valid_label_rate"] == 0.6
    assert metrics["classification_accuracy"] == 0.4
    assert metrics["classification_macro_f1"] == 0.5
    assert metrics["classification_metrics_by_class"] == {
        "A": {"precision": 1.0, "recall": pytest.approx(1 / 3), "f1": 0.5, "support": 3},
        "B": {"precision": 0.5, "recall": 0.5, "f1": 0.5, "support": 2},
    }
    assert metrics["confusion_matrix"] == {
        "A": {"A": 1, "B": 1, "__invalid__": 1},
        "B": {"A": 0, "B": 1, "__invalid__": 1},
    }
    assert metrics["mean_latency_seconds"] == 2.75
    assert metrics["p95_latency_seconds"] == 5.0


@pytest.mark.parametrize("name", ["calculate_metrics", "calculate_classification_metrics"])
def test_empty_evaluation_has_zero_scores_and_no_latency(
    monkeypatch: pytest.MonkeyPatch, name: str
):
    module = load_evaluate_module(monkeypatch)
    metrics = getattr(module, name)([], ["A", "B"])
    assert metrics["samples"] == 0
    assert metrics["json_parse_rate"] == 0
    assert metrics["classification_accuracy"] == 0
    assert metrics["classification_macro_f1"] == 0
    assert metrics["mean_latency_seconds"] is None
    assert metrics["p95_latency_seconds"] is None
