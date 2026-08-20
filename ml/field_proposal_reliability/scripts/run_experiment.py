#!/usr/bin/env python3
"""Train and evaluate the Field Proposal Review Risk Model PoC."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib

os.environ.setdefault("MPLCONFIGDIR", "/tmp/f2_ml_matplotlib_cache")
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    ConfusionMatrixDisplay,
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


RANDOM_STATE = 42
FEATURE_COLUMNS = [
    "field_type",
    "confidence",
    "evidence_length",
    "mention_count",
    "has_conflict",
    "has_negation",
    "parse_success",
]
NUMERIC_FEATURES = [
    "confidence",
    "evidence_length",
    "mention_count",
    "has_conflict",
    "has_negation",
    "parse_success",
]
CATEGORICAL_FEATURES = ["field_type"]
TARGET_COLUMN = "needs_review"
TRACE_COLUMNS = [
    "proposal_id",
    "source_scenario_id",
    "source_group_id",
    "source_transcript_hash",
    "source_dataset",
    "source_label",
    "proxy_risk_score",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--poc-root",
        type=Path,
        default=None,
        help="PoC root. Defaults to the parent of scripts/.",
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=None,
        help="Input CSV. Defaults to <PoC root>/data/synthetic_field_proposals.csv.",
    )
    parser.add_argument(
        "--execution-label",
        default="local_verification",
        help="Execution environment label stored in metrics and the log.",
    )
    parser.add_argument(
        "--verify-notebook-output",
        type=Path,
        default=None,
        help="Verify that an executed .ipynb has no code-cell error outputs, then exit.",
    )
    return parser.parse_args()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def runtime_environment() -> dict[str, Any]:
    try:
        google_colab_available = importlib.util.find_spec("google.colab") is not None
    except ModuleNotFoundError:
        google_colab_available = False
    return {
        "runtime_env": "google_colab" if google_colab_available else "local_or_other",
        "google_colab_import_available": google_colab_available,
        "cwd": str(Path.cwd().resolve()),
        "platform": platform.platform(),
        "python_executable": sys.executable,
    }


def verify_output_notebook(path: Path) -> dict[str, int]:
    notebook = json.loads(path.read_text(encoding="utf-8"))
    code_cells = [cell for cell in notebook.get("cells", []) if cell.get("cell_type") == "code"]
    executed_cells = [cell for cell in code_cells if cell.get("execution_count") is not None]
    error_outputs = [
        output
        for cell in code_cells
        for output in cell.get("outputs", [])
        if output.get("output_type") == "error"
    ]
    result = {
        "code_cell_count": len(code_cells),
        "executed_code_cell_count": len(executed_cells),
        "error_output_count": len(error_outputs),
    }
    if len(executed_cells) != len(code_cells):
        raise AssertionError(
            f"Notebook has unexecuted code cells: {len(executed_cells)}/{len(code_cells)} executed"
        )
    if error_outputs:
        names = [str(output.get("ename", "unknown")) for output in error_outputs]
        raise AssertionError(f"Notebook contains error outputs: {names}")
    print(f"Notebook verification passed: {result}")
    return result


def write_json(payload: Any, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def make_preprocessor(scale_numeric: bool) -> ColumnTransformer:
    numeric_steps: list[tuple[str, Any]] = [("imputer", SimpleImputer(strategy="median"))]
    if scale_numeric:
        numeric_steps.append(("scaler", StandardScaler()))
    return ColumnTransformer(
        transformers=[
            (
                "field_type",
                OneHotEncoder(handle_unknown="ignore"),
                CATEGORICAL_FEATURES,
            ),
            ("numeric", Pipeline(numeric_steps), NUMERIC_FEATURES),
        ],
        remainder="drop",
    )


def make_models() -> dict[str, Any]:
    return {
        "Dummy": DummyClassifier(strategy="most_frequent", random_state=RANDOM_STATE),
        "Logistic Regression": Pipeline(
            steps=[
                ("preprocessor", make_preprocessor(scale_numeric=True)),
                (
                    "classifier",
                    LogisticRegression(max_iter=1000, random_state=RANDOM_STATE),
                ),
            ]
        ),
        "Random Forest": Pipeline(
            steps=[
                ("preprocessor", make_preprocessor(scale_numeric=False)),
                (
                    "classifier",
                    RandomForestClassifier(
                        n_estimators=200,
                        max_depth=6,
                        random_state=RANDOM_STATE,
                    ),
                ),
            ]
        ),
    }


def validate_dataset(frame: pd.DataFrame) -> None:
    required = set(TRACE_COLUMNS + FEATURE_COLUMNS + [TARGET_COLUMN])
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Dataset is missing columns: {missing}")
    if len(frame) != 150:
        raise ValueError(f"Expected 150 rows, found {len(frame)}")
    if frame["proposal_id"].duplicated().any():
        raise ValueError("proposal_id contains duplicates")
    if frame["source_group_id"].duplicated().any():
        raise ValueError("source_group_id contains duplicates")
    if frame[list(required)].isna().sum().sum() != 0:
        raise ValueError("Dataset contains missing values")
    expected_fields = {
        "sale_price",
        "jeonse_deposit",
        "monthly_rent",
        "monthly_deposit",
        "expiry_date",
        "building_number",
        "unit_number",
        "pyeong",
        "deal_type",
        "handover_condition",
    }
    if set(frame["field_type"]) != expected_fields:
        raise ValueError("field_type values do not match the agreed contract")
    if not (frame.groupby("field_type").size() == 15).all():
        raise ValueError("Each field_type must contain exactly 15 rows")
    if frame[TARGET_COLUMN].value_counts().to_dict() != {0: 80, 1: 70}:
        raise ValueError("Target distribution must be LOW_RISK 80 / NEEDS_REVIEW 70")
    if not frame["confidence"].between(0.0, 1.0).all():
        raise ValueError("confidence must be between 0 and 1")
    if not frame["evidence_length"].between(5, 80).all():
        raise ValueError("evidence_length must be between 5 and 80")
    if not frame["mention_count"].between(1, 4).all():
        raise ValueError("mention_count must be between 1 and 4")
    for column in ["has_conflict", "has_negation", "parse_success", TARGET_COLUMN]:
        if not set(frame[column].astype(int)).issubset({0, 1}):
            raise ValueError(f"{column} must be binary")


def make_eda_summary(frame: pd.DataFrame) -> dict[str, Any]:
    return {
        "row_count": int(len(frame)),
        "columns": frame.columns.tolist(),
        "target_distribution": {
            str(key): int(value)
            for key, value in frame[TARGET_COLUMN].value_counts().sort_index().items()
        },
        "target_positive_ratio": float(frame[TARGET_COLUMN].mean()),
        "field_type_distribution": {
            str(key): int(value)
            for key, value in frame["field_type"].value_counts().sort_index().items()
        },
        "missing_values": {
            str(key): int(value) for key, value in frame.isna().sum().items()
        },
        "numeric_summary": json.loads(
            frame[NUMERIC_FEATURES + [TARGET_COLUMN]].describe().round(6).to_json()
        ),
        "first_10_rows": json.loads(frame.head(10).to_json(orient="records")),
    }


def evaluate_model(
    model: Any,
    x_train: pd.DataFrame,
    y_train: pd.Series,
    x_test: pd.DataFrame,
    y_test: pd.Series,
) -> tuple[dict[str, Any], np.ndarray]:
    train_predictions = model.predict(x_train)
    test_predictions = model.predict(x_test)
    matrix = confusion_matrix(y_test, test_predictions, labels=[0, 1])
    result = {
        "train_accuracy": float(accuracy_score(y_train, train_predictions)),
        "test_accuracy": float(accuracy_score(y_test, test_predictions)),
        "precision": float(precision_score(y_test, test_predictions, pos_label=1, zero_division=0)),
        "recall": float(recall_score(y_test, test_predictions, pos_label=1, zero_division=0)),
        "f1": float(f1_score(y_test, test_predictions, pos_label=1, zero_division=0)),
        "train_test_accuracy_gap": float(
            accuracy_score(y_train, train_predictions)
            - accuracy_score(y_test, test_predictions)
        ),
        "confusion_matrix": matrix.tolist(),
        "classification_report": classification_report(
            y_test,
            test_predictions,
            labels=[0, 1],
            target_names=["LOW_RISK", "NEEDS_REVIEW"],
            output_dict=True,
            zero_division=0,
        ),
        "classification_report_text": classification_report(
            y_test,
            test_predictions,
            labels=[0, 1],
            target_names=["LOW_RISK", "NEEDS_REVIEW"],
            zero_division=0,
        ),
    }
    return result, test_predictions


def save_confusion_matrix(
    y_true: pd.Series,
    predictions: np.ndarray,
    title: str,
    output_path: Path,
) -> None:
    figure, axis = plt.subplots(figsize=(5.8, 5.0))
    ConfusionMatrixDisplay.from_predictions(
        y_true,
        predictions,
        labels=[0, 1],
        display_labels=["LOW_RISK", "NEEDS_REVIEW"],
        cmap="Blues",
        colorbar=False,
        ax=axis,
    )
    axis.set_title(title)
    figure.tight_layout()
    figure.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(figure)


def save_random_forest_importance(model: Pipeline, output_path: Path) -> list[dict[str, Any]]:
    preprocessor = model.named_steps["preprocessor"]
    classifier = model.named_steps["classifier"]
    feature_names = preprocessor.get_feature_names_out()
    importance_frame = pd.DataFrame(
        {"feature": feature_names, "importance": classifier.feature_importances_}
    ).sort_values(["importance", "feature"], ascending=[True, True])

    figure_height = max(5.5, 0.34 * len(importance_frame))
    figure, axis = plt.subplots(figsize=(9.0, figure_height))
    axis.barh(importance_frame["feature"], importance_frame["importance"], color="#4C78A8")
    axis.set_title("Random Forest Feature Importance")
    axis.set_xlabel("Importance")
    axis.set_ylabel("Transformed feature")
    figure.tight_layout()
    figure.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(figure)

    return [
        {"feature": str(row.feature), "importance": float(row.importance)}
        for row in importance_frame.sort_values("importance", ascending=False).itertuples()
    ]


def select_final_model(results: dict[str, dict[str, Any]]) -> tuple[str, str]:
    logistic = results["Logistic Regression"]
    forest = results["Random Forest"]
    recall_close = abs(logistic["recall"] - forest["recall"]) <= 0.03
    f1_close = abs(logistic["f1"] - forest["f1"]) <= 0.03
    gap_close = (
        abs(logistic["train_test_accuracy_gap"] - forest["train_test_accuracy_gap"])
        <= 0.03
    )
    if recall_close and f1_close and gap_close:
        return (
            "Logistic Regression",
            "Recall과 F1, Train/Test 성능 차이가 모두 0.03 이내여서 더 단순하고 설명 가능한 Logistic Regression을 선택하였다.",
        )

    candidates = ["Logistic Regression", "Random Forest"]
    selected = max(
        candidates,
        key=lambda name: (
            results[name]["recall"],
            results[name]["f1"],
            -abs(results[name]["train_test_accuracy_gap"]),
            int(name == "Logistic Regression"),
        ),
    )
    result = results[selected]
    other = results[next(name for name in candidates if name != selected)]
    if result["recall"] > other["recall"]:
        reason = (
            f"검토 필요 항목 누락 비용을 고려해 Test Recall이 더 높은 {selected}을 선택하였다."
        )
    elif result["f1"] > other["f1"]:
        reason = f"Test Recall이 같아 Test F1이 더 높은 {selected}을 선택하였다."
    elif abs(result["train_test_accuracy_gap"]) < abs(other["train_test_accuracy_gap"]):
        reason = f"Recall과 F1이 같아 Train/Test 성능 차이가 더 작은 {selected}을 선택하였다."
    else:
        reason = "주요 지표가 같아 더 단순한 Logistic Regression을 선택하였다."
    return selected, reason


def make_markdown_table(comparison: pd.DataFrame) -> str:
    header = "| Model | Train Accuracy | Test Accuracy | Precision | Recall | F1 |"
    separator = "|---|---:|---:|---:|---:|---:|"
    rows = [header, separator]
    for row in comparison.itertuples(index=False):
        rows.append(
            f"| {row.Model} | {row.Train_Accuracy:.4f} | {row.Test_Accuracy:.4f} "
            f"| {row.Precision:.4f} | {row.Recall:.4f} | {row.F1:.4f} |"
        )
    return "\n".join(rows)


def write_experiment_summary(
    comparison: pd.DataFrame,
    final_model_name: str,
    selection_reason: str,
    train_rows: int,
    test_rows: int,
    output_path: Path,
) -> None:
    content = f"""# Field Proposal Review Risk Model 실험 요약

## 1. 실험 목적

F2 sLLM이 생성한 필드 제안 중 사용자의 추가 검토가 필요한 제안을 간단한 머신러닝 모델로 구분할 수 있는지 확인하였다.

## 2. 데이터

기존 프로젝트의 합성 상담 시나리오에서 규칙 기반 Feature와 대리 Target을 파생한 소규모 합성 데이터 150건을 사용하였다. Train {train_rows}건, Test {test_rows}건이며 `needs_review=1` 비율은 46.7%이다. 데이터 생성 및 세부 전처리 과정은 별도 「데이터 전처리 결과서」에서 기술한다.

`needs_review`는 실제 사용자 수락·수정·거절 결과가 아니라 제출용 PoC를 위한 대리 라벨이다. `confidence` 역시 실제 운영 sLLM에서 관측한 값이 아니라 규칙과 고정 난수로 모사한 값이다.

## 3. 모델

- DummyClassifier (다수 클래스 기준선)
- Logistic Regression
- Random Forest

## 4. 평가 지표

`needs_review=1`을 positive class로 두고 Accuracy, Precision, Recall, F1을 계산하였다. 검토 필요 항목의 누락을 줄이는 것이 중요하므로 Recall을 첫 번째 선정 지표로 사용하였다.

## 5. 결과

{make_markdown_table(comparison)}

## 6. 최종 모델 선정

**선정 모델: {final_model_name}**

{selection_reason}

## 7. 한계

- 실제 사용자 데이터가 아닌 합성 상담 시나리오와 규칙 기반 대리 라벨을 사용하였다.
- 데이터 규모가 150건으로 작고 Test Set도 30건에 불과하다.
- 실제 F2 sLLM의 confidence 및 오류 분포와 차이가 있을 수 있다.
- 현재 실험은 모델 적용 가능성을 확인하기 위한 제출용 PoC 수준이다.
- 본 결과는 소규모 합성 Test Set의 결과이며 실서비스 성능을 의미하지 않는다.
- 향후 F2 서비스에서 축적되는 실제 사용자 수락·수정·거절 데이터를 Target으로 전환하여 재학습해야 한다.
- 딥러닝 모델은 이번 PoC 범위에서 학습하지 않았다.
"""
    output_path.write_text(content, encoding="utf-8")


def print_results(
    frame: pd.DataFrame,
    comparison: pd.DataFrame,
    results: dict[str, dict[str, Any]],
    final_model_name: str,
    selection_reason: str,
    train_rows: int,
    test_rows: int,
    generated_files: list[Path],
) -> str:
    lines = [
        "작업 완료",
        "",
        "Dataset",
        f"- 행 수: {len(frame)}",
        f"- Train: {train_rows}",
        f"- Test: {test_rows}",
        f"- Positive class 비율: {frame[TARGET_COLUMN].mean():.4f}",
    ]
    for model_name in ("Logistic Regression", "Random Forest"):
        metrics = results[model_name]
        lines.extend(
            [
                "",
                model_name,
                f"- Accuracy: {metrics['test_accuracy']:.4f}",
                f"- Precision: {metrics['precision']:.4f}",
                f"- Recall: {metrics['recall']:.4f}",
                f"- F1: {metrics['f1']:.4f}",
            ]
        )
    lines.extend(
        [
            "",
            "Final Model",
            f"- 선정 모델: {final_model_name}",
            f"- 선정 이유: {selection_reason}",
            "",
            "Generated Files",
            *[f"- {path}" for path in generated_files],
            "",
            "Model comparison",
            comparison.to_csv(index=False).strip(),
        ]
    )
    output = "\n".join(lines) + "\n"
    print(output)
    return output


def main() -> None:
    args = parse_args()
    if args.verify_notebook_output is not None:
        verify_output_notebook(args.verify_notebook_output.resolve())
        return
    script_path = Path(__file__).resolve()
    poc_root = (args.poc_root or script_path.parent.parent).resolve()
    dataset_path = (
        args.dataset or poc_root / "data/synthetic_field_proposals.csv"
    ).resolve()
    reports_dir = poc_root / "reports"
    artifacts_dir = poc_root / "artifacts"
    reports_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    frame = pd.read_csv(dataset_path)
    validate_dataset(frame)
    eda_summary = make_eda_summary(frame)
    eda_path = reports_dir / "eda_summary.json"
    write_json(eda_summary, eda_path)

    x = frame[FEATURE_COLUMNS].copy()
    y = frame[TARGET_COLUMN].astype(int).copy()
    train_indices, test_indices = train_test_split(
        np.arange(len(frame)),
        test_size=0.20,
        random_state=RANDOM_STATE,
        stratify=y,
    )
    x_train = x.iloc[train_indices].reset_index(drop=True)
    x_test = x.iloc[test_indices].reset_index(drop=True)
    y_train = y.iloc[train_indices].reset_index(drop=True)
    y_test = y.iloc[test_indices].reset_index(drop=True)
    train_groups = set(frame.iloc[train_indices]["source_group_id"])
    test_groups = set(frame.iloc[test_indices]["source_group_id"])
    if train_groups & test_groups:
        raise AssertionError("Source-group leakage detected between Train and Test")
    train_transcripts = set(frame.iloc[train_indices]["source_transcript_hash"])
    test_transcripts = set(frame.iloc[test_indices]["source_transcript_hash"])
    if train_transcripts & test_transcripts:
        raise AssertionError("Transcript leakage detected between Train and Test")
    if set(x_test["field_type"]) != set(frame["field_type"]):
        raise AssertionError("Test split does not contain every field_type")
    if set(y_test) != {0, 1}:
        raise AssertionError("Test split must contain both target classes")

    models = make_models()
    results: dict[str, dict[str, Any]] = {}
    predictions: dict[str, np.ndarray] = {}
    fitted_models: dict[str, Any] = {}
    for name, model in models.items():
        fitted = model.fit(x_train, y_train)
        result, test_predictions = evaluate_model(
            fitted, x_train, y_train, x_test, y_test
        )
        fitted_models[name] = fitted
        results[name] = result
        predictions[name] = test_predictions

    logistic_cm_path = reports_dir / "confusion_matrix_logistic_regression.png"
    forest_cm_path = reports_dir / "confusion_matrix_random_forest.png"
    importance_path = reports_dir / "random_forest_feature_importance.png"
    save_confusion_matrix(
        y_test,
        predictions["Logistic Regression"],
        "Logistic Regression Confusion Matrix",
        logistic_cm_path,
    )
    save_confusion_matrix(
        y_test,
        predictions["Random Forest"],
        "Random Forest Confusion Matrix",
        forest_cm_path,
    )
    forest_importance = save_random_forest_importance(
        fitted_models["Random Forest"], importance_path
    )

    comparison = pd.DataFrame(
        [
            {
                "Model": name,
                "Train Accuracy": result["train_accuracy"],
                "Test Accuracy": result["test_accuracy"],
                "Precision": result["precision"],
                "Recall": result["recall"],
                "F1": result["f1"],
            }
            for name, result in results.items()
        ]
    )
    comparison_path = reports_dir / "model_comparison.csv"
    comparison.to_csv(comparison_path, index=False, encoding="utf-8-sig")
    # Attribute-friendly aliases are used only while rendering Markdown.
    comparison_for_markdown = comparison.rename(
        columns={
            "Train Accuracy": "Train_Accuracy",
            "Test Accuracy": "Test_Accuracy",
        }
    )

    final_model_name, selection_reason = select_final_model(results)
    final_model = fitted_models[final_model_name]
    model_path = artifacts_dir / "field_proposal_review_risk_model.joblib"
    joblib.dump(final_model, model_path)

    versions = {
        "python": platform.python_version(),
        "pandas": pd.__version__,
        "numpy": np.__version__,
        "scikit_learn": sklearn.__version__,
        "matplotlib": matplotlib.__version__,
        "joblib": joblib.__version__,
    }
    runtime = runtime_environment()
    metadata_path = artifacts_dir / "model_metadata.json"
    write_json(
        {
            "generated_at_utc": utc_now(),
            "model_name": final_model_name,
            "task": "binary_classification",
            "target": TARGET_COLUMN,
            "positive_class": 1,
            "positive_class_name": "NEEDS_REVIEW",
            "negative_class_name": "LOW_RISK",
            "random_state": RANDOM_STATE,
            "dataset_type": "synthetic_proxy_label_poc",
            "dataset_path": str(dataset_path),
            "dataset_sha256": sha256_file(dataset_path),
            "feature_columns": FEATURE_COLUMNS,
            "train_rows": int(len(x_train)),
            "test_rows": int(len(x_test)),
            "split": {
                "train_ratio": 0.8,
                "test_ratio": 0.2,
                "stratify": "needs_review",
                "all_field_types_present_in_test": True,
                "source_group_overlap": 0,
                "source_transcript_hash_overlap": 0,
            },
            "selection_priority": [
                "needs_review=1 recall",
                "F1",
                "train/test accuracy gap",
                "model simplicity",
            ],
            "selection_reason": selection_reason,
            "selected_test_metrics": {
                key: value
                for key, value in results[final_model_name].items()
                if key
                in {
                    "test_accuracy",
                    "precision",
                    "recall",
                    "f1",
                    "train_test_accuracy_gap",
                    "confusion_matrix",
                }
            },
            "library_versions": versions,
            "runtime_environment": runtime,
            "execution_label": args.execution_label,
            "limitations": [
                "Synthetic project conversations and proxy labels only.",
                "Simulated confidence; no production sLLM scores.",
                "No real user acceptance/edit/rejection feedback.",
                "PoC artifact only; not integrated with the F2 service.",
            ],
        },
        metadata_path,
    )

    metrics_path = reports_dir / "metrics.json"
    write_json(
        {
            "generated_at_utc": utc_now(),
            "execution_label": args.execution_label,
            "dataset": {
                "path": str(dataset_path),
                "sha256": sha256_file(dataset_path),
                "rows": int(len(frame)),
                "positive_rows": int(y.sum()),
                "positive_ratio": float(y.mean()),
            },
            "split": {
                "train_rows": int(len(x_train)),
                "test_rows": int(len(x_test)),
                "train_target_distribution": {
                    str(key): int(value)
                    for key, value in y_train.value_counts().sort_index().items()
                },
                "test_target_distribution": {
                    str(key): int(value)
                    for key, value in y_test.value_counts().sort_index().items()
                },
                "source_group_overlap": 0,
                "source_transcript_hash_overlap": 0,
            },
            "models": results,
            "random_forest_feature_importance": forest_importance,
            "final_model": {
                "name": final_model_name,
                "selection_reason": selection_reason,
            },
            "library_versions": versions,
            "runtime_environment": runtime,
        },
        metrics_path,
    )

    summary_path = reports_dir / "experiment_summary.md"
    write_experiment_summary(
        comparison_for_markdown,
        final_model_name,
        selection_reason,
        len(x_train),
        len(x_test),
        summary_path,
    )

    # Reloading the artifact proves that the serialized full Pipeline works and
    # that OneHotEncoder(handle_unknown="ignore") handles an unseen field type.
    reloaded_model = joblib.load(model_path)
    smoke_sample = x_test.iloc[[0]].copy()
    unseen_sample = smoke_sample.copy()
    unseen_sample.loc[:, "field_type"] = "future_unknown_field"
    for sample_name, sample in (("known", smoke_sample), ("unknown", unseen_sample)):
        prediction = int(reloaded_model.predict(sample)[0])
        if prediction not in (0, 1):
            raise AssertionError(f"Reload smoke test failed for {sample_name} sample")

    generated_files = [
        eda_path,
        comparison_path,
        metrics_path,
        logistic_cm_path,
        forest_cm_path,
        importance_path,
        summary_path,
        model_path,
        metadata_path,
    ]
    console_output = print_results(
        frame,
        comparison,
        results,
        final_model_name,
        selection_reason,
        len(x_train),
        len(x_test),
        generated_files,
    )
    log_filename = (
        "colab_execution_log.txt"
        if "colab" in args.execution_label.lower()
        else "local_execution_log.txt"
    )
    (reports_dir / log_filename).write_text(
        f"Execution label: {args.execution_label}\n"
        f"Generated at (UTC): {utc_now()}\n"
        f"Python: {versions['python']}\n"
        f"scikit-learn: {versions['scikit_learn']}\n\n"
        f"Runtime environment: {json.dumps(runtime, ensure_ascii=False)}\n\n"
        f"{console_output}",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
