#!/usr/bin/env python3
"""검증된 base model 또는 QLoRA adapter를 SLLM release bundle로 만든다."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CAPABILITY = "f2-consultation-analysis"
SERVED_MODEL_NAME = "sllm"
RELEASE_SCHEMA_VERSION = 2
PROMOTION_APPROVAL_SCHEMA_VERSION = 2
PROMOTION_DECISION_OWNER = "fine-tuning-owner"
RELEASE_MODES = {"lora", "base"}
RELEASE_STAGES = {"verified", "dev"}
RELEASE_ID = re.compile(r"[a-z0-9][a-z0-9._-]{2,63}\Z")
REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*\Z")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
WINDOWS_ABSOLUTE_PATH = re.compile(r"[A-Za-z]:[\\/]")
MAX_ADAPTER_BYTES = 8 * 1024 * 1024 * 1024
EXCLUDED_NAMES = {"checkpoint", "optimizer.pt", "scheduler.pt", "trainer_state.json"}
IGNORED_TRAINING_FILES = {"training_args.bin"}
ALLOWED_ADAPTER_FILES = {
    "README.md",
    "adapter_config.json",
    "adapter_model.safetensors",
    "added_tokens.json",
    "chat_template.jinja",
    "generation_config.json",
    "merges.txt",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer.model",
    "tokenizer_config.json",
    "vocab.json",
}
SENSITIVE_TEXT = re.compile(
    r"(?i)(?:bearer\s+\S+|x-amz-signature|(?:api[_-]?key|password|secret|token)\s*[=:]|"
    r"(?:sk|hf)_[A-Za-z0-9_-]{12,})"
)
PUBLIC_SUMMARY_FIELDS = {
    "run_id",
    "release_mode",
    "dataset_release",
    "dataset_sha256",
    "sample_count",
    "task",
    "quantization",
    "generation",
    "models",
}
PUBLIC_MODEL_FIELDS = {
    "model_id",
    "label",
    "resolved_model_revision",
    "adapter_sha256",
    "samples",
    "json_parse_rate",
    "valid_label_rate",
    "classification_accuracy",
    "classification_macro_f1",
    "classification_f1_by_class",
    "classification_metrics_by_class",
    "confusion_matrix",
    "ledger_mismatch_accuracy",
    "field_precision",
    "field_recall",
    "field_f1",
    "evidence_grounding_violations",
    "unsupported_field_proposals_on_mismatch",
    "mean_latency_seconds",
    "p95_latency_seconds",
    "load_seconds",
    "peak_cuda_memory_bytes",
}


class ReleaseError(ValueError):
    """릴리스 계약 위반."""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReleaseError(f"{label} must be a readable JSON object") from error
    if not isinstance(value, dict):
        raise ReleaseError(f"{label} must be a JSON object")
    return value


def adapter_files(adapter_dir: Path) -> list[Path]:
    if not adapter_dir.is_dir() or adapter_dir.is_symlink():
        raise ReleaseError("adapter directory is unavailable or is a symlink")
    files: list[Path] = []
    size = 0
    for path in sorted(adapter_dir.rglob("*")):
        relative = path.relative_to(adapter_dir)
        if path.is_symlink():
            raise ReleaseError(f"adapter contains a symlink: {relative}")
        if (
            any(part.startswith("checkpoint-") for part in relative.parts)
            or path.name in EXCLUDED_NAMES
        ):
            raise ReleaseError(f"adapter contains a training checkpoint file: {relative}")
        if path.is_file():
            if path.name in IGNORED_TRAINING_FILES:
                continue
            if relative.as_posix() not in ALLOWED_ADAPTER_FILES:
                raise ReleaseError(f"adapter contains an unapproved file: {relative}")
            size += path.stat().st_size
            if size > MAX_ADAPTER_BYTES:
                raise ReleaseError("adapter exceeds the 8 GiB release limit")
            files.append(path)
    required = {"adapter_config.json", "adapter_model.safetensors"}
    missing = required - {path.name for path in files}
    if missing:
        raise ReleaseError("adapter is missing required files: " + ", ".join(sorted(missing)))
    return files


def tree_sha256(root: Path, files: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in files:
        relative = path.relative_to(root).as_posix().encode()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(file_sha256(path)))
    return digest.hexdigest()


def _nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReleaseError(f"{label} must be a non-empty string")
    return value.strip()


def _aggregate_value(value: Any, label: str) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, dict):
        return {
            _public_text(name, f"{label} key"): _aggregate_value(item, f"{label}.{name}")
            for name, item in value.items()
        }
    raise ReleaseError(f"{label} may contain aggregate numbers, booleans and objects only")


def _safe_identifier(value: Any, label: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ReleaseError(f"{label} is invalid")
    return value


def _public_text(value: Any, label: str) -> str:
    text = _nonempty_string(value, label)
    if (
        text.startswith("/")
        or WINDOWS_ABSOLUTE_PATH.match(text)
        or "\\" in text
        or SENSITIVE_TEXT.search(text)
    ):
        raise ReleaseError(f"{label} contains a path or secret-like value")
    return text


def _resolved_path(value: Any, label: str) -> Path | None:
    if value is None:
        return None
    raw = _nonempty_string(value, label)
    if WINDOWS_ABSOLUTE_PATH.match(raw):
        return Path(raw)
    return Path(raw).resolve()


def public_evaluation_summary(evaluation: dict[str, Any]) -> dict[str, Any]:
    unexpected = set(evaluation) - (
        PUBLIC_SUMMARY_FIELDS | {"dataset", "adapter_path", "adapter_sha256"}
    )
    if unexpected:
        raise ReleaseError(
            "evaluation summary contains unsupported fields: " + ", ".join(sorted(unexpected))
        )
    public: dict[str, Any] = {}
    for field in PUBLIC_SUMMARY_FIELDS - {"generation", "models"}:
        if field not in evaluation:
            raise ReleaseError(f"evaluation summary is missing {field}")
        public[field] = evaluation[field]
    if "generation" not in evaluation:
        raise ReleaseError("evaluation summary is missing generation")
    public["generation"] = _aggregate_value(evaluation.get("generation"), "generation")
    models = evaluation.get("models")
    if not isinstance(models, list) or not models:
        raise ReleaseError("evaluation summary must contain at least one model result")
    sanitized_models: list[dict[str, Any]] = []
    for index, model in enumerate(models):
        if not isinstance(model, dict):
            raise ReleaseError("every evaluation model result must be an object")
        unexpected_model = set(model) - (PUBLIC_MODEL_FIELDS | {"adapter_path"})
        if unexpected_model:
            raise ReleaseError(
                f"evaluation model {index} contains unsupported fields: "
                + ", ".join(sorted(unexpected_model))
            )
        sanitized: dict[str, Any] = {}
        for field in ("model_id", "label", "resolved_model_revision"):
            if field not in model:
                raise ReleaseError(f"evaluation model {index} is missing {field}")
            sanitized[field] = model[field]
        sanitized["adapter_sha256"] = model.get("adapter_sha256")
        for field in sorted(PUBLIC_MODEL_FIELDS - set(sanitized)):
            if field in model:
                sanitized[field] = _aggregate_value(model[field], f"models[{index}].{field}")
        sanitized_models.append(sanitized)
    public["models"] = sanitized_models
    return public


def validate_evaluation(
    evaluation: dict[str, Any], *, dataset_release: str, release_mode: str
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if evaluation.get("task") != "full":
        raise ReleaseError("consultation-analysis release requires a full-task evaluation summary")
    if evaluation.get("dataset_release") != dataset_release:
        raise ReleaseError("dataset-release must match the evaluation summary")
    if evaluation.get("release_mode") != release_mode:
        raise ReleaseError("release-mode must match the evaluation summary")
    _safe_identifier(evaluation.get("dataset_sha256"), "evaluation dataset checksum", SHA256)
    public = public_evaluation_summary(evaluation)
    models = evaluation["models"]
    assert isinstance(models, list)
    labels: list[str] = []
    for index, model in enumerate(models):
        assert isinstance(model, dict)
        label = _safe_identifier(model.get("label"), f"evaluation model {index} label", REFERENCE)
        _safe_identifier(model.get("model_id"), f"evaluation model {index} id", MODEL_ID)
        _safe_identifier(
            model.get("resolved_model_revision"),
            f"evaluation model {index} revision",
            COMMIT,
        )
        adapter_hash = model.get("adapter_sha256")
        if adapter_hash is not None:
            _safe_identifier(adapter_hash, f"evaluation model {index} adapter hash", SHA256)
        labels.append(label)
    if len(set(labels)) != len(labels):
        raise ReleaseError("evaluation model labels must be unique")
    top_adapter_path = evaluation.get("adapter_path")
    top_adapter_hash = evaluation.get("adapter_sha256")
    model_has_adapter = any(
        model.get("adapter_path") is not None or model.get("adapter_sha256") is not None
        for model in models
    )
    if release_mode == "base":
        if top_adapter_path is not None or top_adapter_hash is not None or model_has_adapter:
            raise ReleaseError("base release evaluation must not use an adapter")
    else:
        _nonempty_string(top_adapter_path, "evaluation adapter_path")
        _safe_identifier(top_adapter_hash, "evaluation adapter checksum", SHA256)
        if len(models) != 1 or any(
            model.get("adapter_sha256") != top_adapter_hash
            or model.get("adapter_path") != top_adapter_path
            for model in models
        ):
            raise ReleaseError("lora evaluation must contain exactly one matching adapter model")
    return models, public


def validate_promotion_approval(
    evaluation: dict[str, Any], approval: dict[str, Any], *, release_mode: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    required = {
        "schema_version",
        "status",
        "release_mode",
        "evaluation_run_id",
        "selected_model",
        "decision_owner",
        "rationale",
    }
    if set(approval) != required:
        raise ReleaseError("promotion approval has an invalid schema")
    if approval.get("schema_version") != PROMOTION_APPROVAL_SCHEMA_VERSION:
        raise ReleaseError("promotion approval schema_version must be 2")
    if approval.get("status") != "approved":
        raise ReleaseError("promotion approval status must be approved")
    if approval.get("release_mode") != release_mode:
        raise ReleaseError("promotion approval release_mode must match the requested release")
    evaluation_run_id = _nonempty_string(evaluation.get("run_id"), "evaluation run_id")
    if approval.get("evaluation_run_id") != evaluation_run_id:
        raise ReleaseError("promotion approval evaluation_run_id must match the evaluation summary")
    models = evaluation.get("models")
    assert isinstance(models, list)
    selected_model = approval.get("selected_model")
    selected = next(
        (
            model
            for model in models
            if isinstance(model, dict) and model.get("label") == selected_model
        ),
        None,
    )
    if selected is None:
        raise ReleaseError("promotion approval selected_model must exist in evaluation results")
    if approval.get("decision_owner") != PROMOTION_DECISION_OWNER:
        raise ReleaseError("promotion approval decision_owner must be fine-tuning-owner")
    rationale = _public_text(approval.get("rationale"), "promotion approval rationale")
    return (
        {
            "schema_version": PROMOTION_APPROVAL_SCHEMA_VERSION,
            "status": "approved",
            "release_mode": release_mode,
            "evaluation_run_id": evaluation_run_id,
            "selected_model": selected_model,
            "decision_owner": PROMOTION_DECISION_OWNER,
            "rationale": rationale,
        },
        selected,
    )


def _lora_source(
    training_output: Path, selected: dict[str, Any] | None
) -> tuple[dict[str, Any], dict[str, Any], Path, list[Path]]:
    metadata = json_object(training_output / "run_metadata.json", "run metadata")
    adapter_dir = training_output / "adapter"
    files = adapter_files(adapter_dir)
    adapter_hash = tree_sha256(adapter_dir, files)
    config = metadata.get("config")
    data = metadata.get("data")
    if not isinstance(config, dict) or not isinstance(config.get("model"), dict):
        raise ReleaseError("run metadata is missing config.model")
    if not isinstance(data, dict):
        raise ReleaseError("run metadata is missing data hashes")
    model_id = _safe_identifier(config["model"].get("id"), "run metadata base model id", MODEL_ID)
    revision = metadata.get("resolved_model_revision") or config["model"].get("revision")
    revision = _safe_identifier(revision, "run metadata base model revision", COMMIT)
    if selected is not None:
        if (
            selected.get("model_id") != model_id
            or selected.get("resolved_model_revision") != revision
        ):
            raise ReleaseError("selected evaluation model does not match the trained base model")
        if selected.get("adapter_sha256") != adapter_hash:
            raise ReleaseError(
                "selected evaluation adapter checksum does not match the packaged adapter"
            )
        evaluated_path = _resolved_path(
            selected.get("adapter_path"), "selected evaluation adapter_path"
        )
        if evaluated_path is None or evaluated_path != adapter_dir.resolve():
            raise ReleaseError(
                "selected evaluation adapter path does not match the packaged adapter"
            )
    adapter_config = json_object(adapter_dir / "adapter_config.json", "adapter config")
    if adapter_config.get("base_model_name_or_path") != model_id:
        raise ReleaseError("adapter config base model does not match run metadata")
    hashes: dict[str, str] = {}
    for split in ("train", "validation"):
        entry = data.get(split)
        value = entry.get("sha256") if isinstance(entry, dict) else None
        hashes[split] = _safe_identifier(value, f"run metadata {split} hash", SHA256)
    adapter = {
        "format": "peft-lora",
        "path": "adapter",
        "sha256": adapter_hash,
        "size_bytes": sum(path.stat().st_size for path in files),
        "file_count": len(files),
    }
    code_revision = metadata.get("git_revision")
    if code_revision is not None:
        code_revision = _safe_identifier(code_revision, "run metadata code revision", COMMIT)
    training = {
        "code_revision": code_revision,
        "train_sha256": hashes["train"],
        "validation_sha256": hashes["validation"],
    }
    return (
        {"id": model_id, "revision": revision},
        {"adapter": adapter, "training": training},
        adapter_dir,
        files,
    )


def build_manifest(
    *,
    release_id: str,
    release_mode: str,
    release_stage: str,
    base_model: dict[str, Any],
    source: dict[str, Any],
    evaluation: dict[str, Any] | None,
    source_evaluation_sha256: str | None,
    evaluation_sha256: str | None,
    approval: dict[str, Any] | None,
    approval_sha256: str | None,
    dataset_release: str,
) -> dict[str, Any]:
    if RELEASE_ID.fullmatch(release_id) is None:
        raise ReleaseError("release-id must contain 3-64 lowercase URL-safe characters")
    if release_stage == "verified":
        assert evaluation is not None
        assert approval is not None
        assert source_evaluation_sha256 is not None
        assert evaluation_sha256 is not None
        assert approval_sha256 is not None
        evaluation_contract: dict[str, Any] = {
            "task": "full",
            "dataset_release": dataset_release,
            "dataset_sha256": evaluation["dataset_sha256"],
            "source_summary_sha256": source_evaluation_sha256,
            "summary_path": "evaluation-summary.json",
            "summary_sha256": evaluation_sha256,
            "promotion_status": approval["status"],
            "selected_model": approval["selected_model"],
            "approval_path": "promotion-approval.json",
            "approval_sha256": approval_sha256,
        }
    else:
        evaluation_contract = {
            "status": "not-evaluated",
            "dataset_release": dataset_release,
        }
    return {
        "schema_version": RELEASE_SCHEMA_VERSION,
        "release_id": release_id,
        "release_mode": release_mode,
        "release_stage": release_stage,
        "capability": CAPABILITY,
        "served_model_name": SERVED_MODEL_NAME,
        "created_at": datetime.now(UTC).isoformat(),
        "base_model": base_model,
        "adapter": source["adapter"],
        "training": source["training"],
        "evaluation": evaluation_contract,
    }


def package_release(
    *,
    release_id: str,
    release_mode: str,
    training_output: Path | None,
    evaluation_summary: Path | None,
    promotion_approval: Path | None,
    dataset_release: str,
    output: Path,
    release_stage: str = "verified",
    base_model_id: str | None = None,
    base_model_revision: str | None = None,
) -> dict[str, Any]:
    if output.exists():
        raise ReleaseError(f"output already exists: {output}")
    if release_mode not in RELEASE_MODES:
        raise ReleaseError("release-mode must be lora or base")
    if release_stage not in RELEASE_STAGES:
        raise ReleaseError("release-stage must be verified or dev")
    if release_stage == "dev" and not release_id.startswith("dev-"):
        raise ReleaseError("dev release-id must start with dev-")
    if (release_mode == "lora") != (training_output is not None):
        raise ReleaseError("lora requires --training-output and base forbids it")
    dataset_release = _safe_identifier(dataset_release, "dataset-release", REFERENCE)
    if release_stage == "verified":
        if evaluation_summary is None or promotion_approval is None:
            raise ReleaseError(
                "verified release requires evaluation summary and promotion approval"
            )
        if base_model_id is not None or base_model_revision is not None:
            raise ReleaseError("verified release derives the base model from evaluation")
        evaluation = json_object(evaluation_summary, "evaluation summary")
        validate_evaluation(evaluation, dataset_release=dataset_release, release_mode=release_mode)
        approval, selected = validate_promotion_approval(
            evaluation,
            json_object(promotion_approval, "promotion approval"),
            release_mode=release_mode,
        )
    else:
        if evaluation_summary is not None or promotion_approval is not None:
            raise ReleaseError("dev release forbids evaluation summary and promotion approval")
        evaluation = None
        approval = None
        selected = None
    if release_mode == "lora":
        if base_model_id is not None or base_model_revision is not None:
            raise ReleaseError("lora release derives the base model from training metadata")
        assert training_output is not None
        base_model, source, adapter_dir, files = _lora_source(training_output, selected)
    else:
        if release_stage == "verified":
            assert selected is not None and evaluation is not None
            if (
                selected.get("adapter_path") is not None
                or selected.get("adapter_sha256") is not None
            ):
                raise ReleaseError("base release evaluation must not use an adapter")
            if (
                evaluation.get("adapter_path") is not None
                or evaluation.get("adapter_sha256") is not None
            ):
                raise ReleaseError("base release summary must not use an adapter")
            base_model = {
                "id": _safe_identifier(
                    selected.get("model_id"), "selected base model id", MODEL_ID
                ),
                "revision": _safe_identifier(
                    selected.get("resolved_model_revision"),
                    "selected base model revision",
                    COMMIT,
                ),
            }
        else:
            base_model = {
                "id": _safe_identifier(base_model_id, "dev base model id", MODEL_ID),
                "revision": _safe_identifier(
                    base_model_revision,
                    "dev base model revision",
                    COMMIT,
                ),
            }
        source = {"adapter": None, "training": None}
        adapter_dir = None
        files = []

    evaluation_bytes = None
    approval_bytes = None
    if evaluation is not None and approval is not None:
        public_evaluation = public_evaluation_summary(evaluation)
        evaluation_bytes = (
            json.dumps(public_evaluation, ensure_ascii=False, indent=2) + "\n"
        ).encode()
        approval_bytes = (json.dumps(approval, ensure_ascii=False, indent=2) + "\n").encode()
    manifest = build_manifest(
        release_id=release_id,
        release_mode=release_mode,
        release_stage=release_stage,
        base_model=base_model,
        source=source,
        evaluation=evaluation,
        source_evaluation_sha256=(
            file_sha256(evaluation_summary) if evaluation_summary is not None else None
        ),
        evaluation_sha256=(
            hashlib.sha256(evaluation_bytes).hexdigest() if evaluation_bytes is not None else None
        ),
        approval=approval,
        approval_sha256=(
            hashlib.sha256(approval_bytes).hexdigest() if approval_bytes is not None else None
        ),
        dataset_release=dataset_release,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode()
    with tarfile.open(output, "w:gz", format=tarfile.PAX_FORMAT) as archive:
        contents = [("release.json", manifest_bytes)]
        if evaluation_bytes is not None and approval_bytes is not None:
            contents.extend(
                [
                    ("evaluation-summary.json", evaluation_bytes),
                    ("promotion-approval.json", approval_bytes),
                ]
            )
        for name, content in contents:
            info = tarfile.TarInfo(name)
            info.size = len(content)
            info.mode = 0o600
            info.mtime = 0
            archive.addfile(info, io.BytesIO(content))
        if adapter_dir is not None:
            for path in files:
                name = f"adapter/{path.relative_to(adapter_dir).as_posix()}"
                info = tarfile.TarInfo(name)
                info.size = path.stat().st_size
                info.mode = 0o600
                info.mtime = 0
                with path.open("rb") as source_file:
                    archive.addfile(info, source_file)

    result = {
        "release_id": release_id,
        "release_mode": release_mode,
        "release_stage": release_stage,
        "bundle": str(output),
        "bundle_sha256": file_sha256(output),
        "size_bytes": output.stat().st_size,
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return result


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--release-id", required=True)
    cli.add_argument("--release-mode", required=True, choices=sorted(RELEASE_MODES))
    cli.add_argument("--release-stage", default="verified", choices=sorted(RELEASE_STAGES))
    cli.add_argument("--training-output", type=Path)
    cli.add_argument("--evaluation-summary", type=Path)
    cli.add_argument("--promotion-approval", type=Path)
    cli.add_argument("--base-model-id")
    cli.add_argument("--base-model-revision")
    cli.add_argument("--dataset-release", required=True)
    cli.add_argument("--output", type=Path, required=True)
    return cli


def main() -> int:
    arguments = parser().parse_args()
    try:
        package_release(
            release_id=arguments.release_id,
            release_mode=arguments.release_mode,
            training_output=arguments.training_output,
            evaluation_summary=arguments.evaluation_summary,
            promotion_approval=arguments.promotion_approval,
            dataset_release=arguments.dataset_release,
            output=arguments.output,
            release_stage=arguments.release_stage,
            base_model_id=arguments.base_model_id,
            base_model_revision=arguments.base_model_revision,
        )
    except ReleaseError as error:
        print(json.dumps({"event": "error", "message": str(error)}, ensure_ascii=False))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
