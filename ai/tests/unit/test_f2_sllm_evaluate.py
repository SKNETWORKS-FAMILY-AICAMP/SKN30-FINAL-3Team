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
