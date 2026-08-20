"""Validate the temporary ML PoC artifacts and the two final DOCX files."""

from __future__ import annotations

import csv
import hashlib
import html
import json
import math
import re
from collections import Counter
from pathlib import Path
from zipfile import ZipFile

import joblib
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
DOCUMENTS = ROOT / "documents"
TRAINING_NAME = "[데이터 전처리] 머신러닝_딥러닝 학습 결과서_30기_3팀.docx"
MODEL_NAME = "[데이터 전처리] 학습한 ML_DL 모델_30기_3팀.docx"
REFERENCE_DOCS = {
    Path("/mnt/c/Users/playdata2/Downloads/[데이터 전처리] 머신러닝_딥러닝 학습 결과서_27기_1팀.docx"):
        "8412009a919c7728590ac6518c349f70c5c6f52bfb3fb1361898107c68e54631",
    Path("/mnt/c/Users/playdata2/Downloads/[데이터 전처리] 학습한 ML_DL 모델_27기_1팀.docx"):
        "6c7b57cf9a391c3f428917c1ed306b67b7fceb7aecf7180796f05943526321ae",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def docx_text(path: Path) -> str:
    parts: list[str] = []
    with ZipFile(path) as archive:
        for name in archive.namelist():
            if not (
                name == "word/document.xml"
                or name.startswith("word/header")
                or name.startswith("word/footer")
            ):
                continue
            raw = archive.read(name).decode("utf-8", errors="replace")
            parts.append(html.unescape(re.sub(r"<[^>]+>", "", raw)))
    return "\n".join(parts)


def notebook_status(path: Path) -> dict[str, int]:
    notebook = json.loads(path.read_text(encoding="utf-8"))
    code_cells = [cell for cell in notebook["cells"] if cell["cell_type"] == "code"]
    executed = [cell for cell in code_cells if cell.get("execution_count") is not None]
    errors = [
        output
        for cell in code_cells
        for output in cell.get("outputs", [])
        if output.get("output_type") == "error"
    ]
    return {"code_cells": len(code_cells), "executed_code_cells": len(executed), "error_outputs": len(errors)}


def close(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-9)


def main() -> None:
    metrics = json.loads((ROOT / "reports/metrics.json").read_text(encoding="utf-8"))
    metadata = json.loads((ROOT / "artifacts/model_metadata.json").read_text(encoding="utf-8"))
    inventory = json.loads((ROOT / "data/source_inventory.json").read_text(encoding="utf-8"))
    colab = json.loads((ROOT / "reports/colab_execution_status.json").read_text(encoding="utf-8"))

    training_doc = DOCUMENTS / TRAINING_NAME
    model_doc = DOCUMENTS / MODEL_NAME
    final_docs = sorted(path.name for path in DOCUMENTS.glob("*.docx"))
    training_text = docx_text(training_doc)
    model_text = docx_text(model_doc)
    combined_text = training_text + "\n" + model_text

    data_path = ROOT / "data/synthetic_field_proposals.csv"
    frame = pd.read_csv(data_path)
    feature_columns = metadata["feature_columns"]
    target_distribution = {str(key): int(value) for key, value in frame["needs_review"].value_counts().sort_index().items()}
    field_distribution = {str(key): int(value) for key, value in frame["field_type"].value_counts().sort_index().items()}

    comparison_rows: dict[str, dict[str, float]] = {}
    with (ROOT / "reports/model_comparison.csv").open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            comparison_rows[row["Model"]] = {key: float(value) for key, value in row.items() if key != "Model"}

    metric_checks: dict[str, bool] = {}
    for name, result in metrics["models"].items():
        tn, fp = result["confusion_matrix"][0]
        fn, tp = result["confusion_matrix"][1]
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        accuracy = (tn + tp) / (tn + fp + fn + tp)
        csv_result = comparison_rows[name]
        metric_checks[name] = all(
            (
                close(accuracy, result["test_accuracy"]),
                close(precision, result["precision"]),
                close(recall, result["recall"]),
                close(f1, result["f1"]),
                close(csv_result["Test Accuracy"], result["test_accuracy"]),
                close(csv_result["Precision"], result["precision"]),
                close(csv_result["Recall"], result["recall"]),
                close(csv_result["F1"], result["f1"]),
            )
        )

    selected = metrics["models"][metrics["final_model"]["name"]]
    expected_numbers = {
        f"{result[key]:.4f}"
        for result in metrics["models"].values()
        for key in ("train_accuracy", "test_accuracy", "precision", "recall", "f1")
    }
    banned = [
        "27기",
        "1팀",
        "김경수",
        "SKN27-FINAL-1Team",
        "LightFM",
        "레시피",
        "실제 사용자 데이터를 학습하였다",
        "실서비스 환경에서 성능이 검증되었다",
        "실제 중개 상담에서 높은 정확도를 달성하였다",
        "업무 시간을 절감하였다",
    ]

    pipeline = joblib.load(ROOT / "artifacts/field_proposal_review_risk_model.joblib")
    normal_predictions = pipeline.predict(frame[feature_columns].head(3)).tolist()
    unknown = frame[feature_columns].head(1).copy()
    unknown.loc[:, "field_type"] = "future_unknown_field"
    unknown_predictions = pipeline.predict(unknown).tolist()

    training_structure = json.loads((ROOT / "qa/final-structure/training-result/structure_audit.json").read_text(encoding="utf-8"))
    model_structure = json.loads((ROOT / "qa/final-structure/trained-model/structure_audit.json").read_text(encoding="utf-8"))
    notebook = notebook_status(ROOT / "notebooks/field_proposal_review_risk_poc_output.ipynb")

    checks = {
        "exactly_two_final_docx": final_docs == sorted([TRAINING_NAME, MODEL_NAME]),
        "final_docx_nonempty": training_doc.stat().st_size > 0 and model_doc.stat().st_size > 0,
        "reference_templates_unchanged": all(path.exists() and sha256(path) == expected for path, expected in REFERENCE_DOCS.items()),
        "dataset_sha_matches_metrics": sha256(data_path) == metrics["dataset"]["sha256"] == metadata["dataset_sha256"],
        "dataset_contract": (
            len(frame) == 150
            and frame.isna().sum().sum() == 0
            and target_distribution == {"0": 80, "1": 70}
            and len(field_distribution) == 10
            and set(field_distribution.values()) == {15}
            and frame["proposal_id"].is_unique
            and frame["source_group_id"].is_unique
            and frame["source_transcript_hash"].is_unique
        ),
        "source_inventory_contract": inventory["raw_row_count"] == 1250 and inventory["deduplicated_row_count"] == 1200 and inventory["duplicate_row_count"] == 50,
        "split_contract": metrics["split"]["train_rows"] == 120 and metrics["split"]["test_rows"] == 30 and metrics["split"]["source_group_overlap"] == 0 and metrics["split"]["source_transcript_hash_overlap"] == 0,
        "metric_recomputation": all(metric_checks.values()),
        "selected_model_consistent": metrics["final_model"]["name"] == metadata["model_name"] == "Logistic Regression" and metrics["final_model"]["selection_reason"] == metadata["selection_reason"],
        "selected_metric_contract": close(selected["test_accuracy"], 0.8) and close(selected["precision"], 0.9) and close(selected["recall"], 9 / 14) and close(selected["f1"], 0.75),
        "docx_numbers_match": all(number in training_text and number in model_text for number in expected_numbers),
        "docx_model_and_reason_match": all(token in training_text and token in model_text for token in (metrics["final_model"]["name"], metrics["final_model"]["selection_reason"])),
        "docx_disclosures_present": all(token in combined_text for token in ("합성", "대리", "실서비스 성능", "실제 사용자", "딥러닝", "Test 30건")),
        "split_description_matches_code": "복합 층화" not in combined_text and "needs_review 기준 층화 분할" in training_text and "Test에 10개 field_type이 모두 포함되는지 별도 검증" in training_text,
        "forbidden_legacy_or_claim_text_absent": not any(token in combined_text for token in banned),
        "model_reload_smoke": len(normal_predictions) == 3 and len(unknown_predictions) == 1 and set(normal_predictions + unknown_predictions) <= {0, 1},
        "notebook_executed_without_errors": notebook == {"code_cells": 4, "executed_code_cells": 4, "error_outputs": 0},
        "colab_status_honest": colab["status"] == "not_executed" and colab["remote_results_claimed"] is False and colab["available_verified_run"] == "local_notebook_verification",
        "training_docx_structure": training_structure["structural_qa"]["zip_test"] and training_structure["structural_qa"]["required_parts_present"] and training_structure["structural_qa"]["duplicate_docpr_ids"] == [],
        "model_docx_structure": model_structure["structural_qa"]["zip_test"] and model_structure["structural_qa"]["required_parts_present"] and model_structure["structural_qa"]["duplicate_docpr_ids"] == [],
        "rendered_all_pages": len(list((ROOT / "qa/document-renders/training-result-v4").glob("*.png"))) == 9 and len(list((ROOT / "qa/document-renders/trained-model-v2").glob("*.png"))) == 5,
    }

    result = {
        "all_checks_passed": all(checks.values()),
        "checks": checks,
        "final_documents": {
            TRAINING_NAME: {"sha256": sha256(training_doc), "bytes": training_doc.stat().st_size, "rendered_pages": 9},
            MODEL_NAME: {"sha256": sha256(model_doc), "bytes": model_doc.stat().st_size, "rendered_pages": 5},
        },
        "dataset": {"rows": len(frame), "target_distribution": target_distribution, "field_type_distribution": field_distribution, "sha256": sha256(data_path)},
        "model": {"name": metrics["final_model"]["name"], "test_accuracy": selected["test_accuracy"], "precision": selected["precision"], "recall": selected["recall"], "f1": selected["f1"], "reload_predictions": normal_predictions, "unknown_field_prediction": unknown_predictions},
        "notebook": notebook,
        "colab": colab,
    }
    output = ROOT / "qa/final_validation.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["all_checks_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
