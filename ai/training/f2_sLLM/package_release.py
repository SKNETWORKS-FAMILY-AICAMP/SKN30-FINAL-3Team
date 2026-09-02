#!/usr/bin/env python3
"""검증된 QLoRA adapter를 Infra에 전달할 SLLM release bundle로 만든다."""

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
PROMOTION_APPROVAL_SCHEMA_VERSION = 1
PROMOTION_DECISION_OWNER = "fine-tuning-owner"
RELEASE_ID = re.compile(r"[a-z0-9][a-z0-9._-]{2,63}\Z")
MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*\Z")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
MAX_ADAPTER_BYTES = 8 * 1024 * 1024 * 1024
EXCLUDED_NAMES = {"checkpoint", "optimizer.pt", "scheduler.pt", "trainer_state.json"}


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


def validate_promotion_approval(
    evaluation: dict[str, Any], approval: dict[str, Any]
) -> dict[str, Any]:
    if approval.get("schema_version") != PROMOTION_APPROVAL_SCHEMA_VERSION:
        raise ReleaseError("promotion approval schema_version must be 1")
    if approval.get("status") != "approved":
        raise ReleaseError("promotion approval status must be approved")

    evaluation_run_id = evaluation.get("run_id")
    if not isinstance(evaluation_run_id, str) or not evaluation_run_id.strip():
        raise ReleaseError("evaluation summary must contain a non-empty run_id")
    if approval.get("evaluation_run_id") != evaluation_run_id:
        raise ReleaseError("promotion approval evaluation_run_id must match the evaluation summary")

    models = evaluation.get("models")
    if not isinstance(models, list) or not models:
        raise ReleaseError("evaluation summary must contain at least one model result")
    labels = [model.get("label") for model in models if isinstance(model, dict)]
    if len(labels) != len(models) or any(
        not isinstance(label, str) or not label.strip() for label in labels
    ):
        raise ReleaseError("every evaluation model result must contain a non-empty label")
    if len(set(labels)) != len(labels):
        raise ReleaseError("evaluation model labels must be unique")

    selected_model = approval.get("selected_model")
    if selected_model not in labels:
        raise ReleaseError("promotion approval selected_model must exist in evaluation results")
    if approval.get("decision_owner") != PROMOTION_DECISION_OWNER:
        raise ReleaseError("promotion approval decision_owner must be fine-tuning-owner")
    rationale = approval.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        raise ReleaseError("promotion approval rationale must be a non-empty string")

    return {
        "schema_version": PROMOTION_APPROVAL_SCHEMA_VERSION,
        "status": "approved",
        "evaluation_run_id": evaluation_run_id,
        "selected_model": selected_model,
        "decision_owner": PROMOTION_DECISION_OWNER,
        "rationale": rationale.strip(),
    }


def build_manifest(
    *,
    release_id: str,
    metadata: dict[str, Any],
    evaluation: dict[str, Any],
    evaluation_sha256: str,
    approval: dict[str, Any],
    approval_sha256: str,
    adapter_dir: Path,
    files: list[Path],
    dataset_release: str,
) -> dict[str, Any]:
    if RELEASE_ID.fullmatch(release_id) is None:
        raise ReleaseError("release-id must contain 3-64 lowercase URL-safe characters")
    config = metadata.get("config")
    data = metadata.get("data")
    if not isinstance(config, dict) or not isinstance(config.get("model"), dict):
        raise ReleaseError("run metadata is missing config.model")
    if not isinstance(data, dict):
        raise ReleaseError("run metadata is missing data hashes")
    model_id = config["model"].get("id")
    revision = metadata.get("resolved_model_revision") or config["model"].get("revision")
    if not isinstance(model_id, str) or MODEL_ID.fullmatch(model_id) is None:
        raise ReleaseError("run metadata base model id is invalid")
    if not isinstance(revision, str) or COMMIT.fullmatch(revision) is None:
        raise ReleaseError("base model revision must be an immutable 40-character commit")
    if evaluation.get("task") != "full":
        raise ReleaseError("consultation-analysis release requires a full-task evaluation summary")

    hashes: dict[str, str] = {}
    for split in ("train", "validation"):
        entry = data.get(split)
        value = entry.get("sha256") if isinstance(entry, dict) else None
        if not isinstance(value, str) or SHA256.fullmatch(value) is None:
            raise ReleaseError(f"run metadata is missing a valid {split} hash")
        hashes[split] = value

    total_size = sum(path.stat().st_size for path in files)
    return {
        "schema_version": 1,
        "release_id": release_id,
        "capability": CAPABILITY,
        "served_model_name": SERVED_MODEL_NAME,
        "created_at": datetime.now(UTC).isoformat(),
        "base_model": {"id": model_id, "revision": revision},
        "adapter": {
            "format": "peft-lora",
            "path": "adapter",
            "sha256": tree_sha256(adapter_dir, files),
            "size_bytes": total_size,
            "file_count": len(files),
        },
        "training": {
            "code_revision": metadata.get("git_revision"),
            "dataset_release": dataset_release,
            "train_sha256": hashes["train"],
            "validation_sha256": hashes["validation"],
        },
        "evaluation": {
            "task": "full",
            "summary_path": "evaluation-summary.json",
            "summary_sha256": evaluation_sha256,
            "promotion_status": approval["status"],
            "selected_model": approval["selected_model"],
            "approval_path": "promotion-approval.json",
            "approval_sha256": approval_sha256,
        },
    }


def package_release(
    *,
    release_id: str,
    training_output: Path,
    evaluation_summary: Path,
    promotion_approval: Path,
    dataset_release: str,
    output: Path,
) -> dict[str, Any]:
    if output.exists():
        raise ReleaseError(f"output already exists: {output}")
    metadata_path = training_output / "run_metadata.json"
    adapter_dir = training_output / "adapter"
    metadata = json_object(metadata_path, "run metadata")
    evaluation = json_object(evaluation_summary, "evaluation summary")
    approval = validate_promotion_approval(
        evaluation, json_object(promotion_approval, "promotion approval")
    )
    public_evaluation = {
        name: value for name, value in evaluation.items() if name not in {"dataset", "adapter_path"}
    }
    evaluation_bytes = (json.dumps(public_evaluation, ensure_ascii=False, indent=2) + "\n").encode()
    approval_bytes = (json.dumps(approval, ensure_ascii=False, indent=2) + "\n").encode()
    files = adapter_files(adapter_dir)
    manifest = build_manifest(
        release_id=release_id,
        metadata=metadata,
        evaluation=evaluation,
        evaluation_sha256=hashlib.sha256(evaluation_bytes).hexdigest(),
        approval=approval,
        approval_sha256=hashlib.sha256(approval_bytes).hexdigest(),
        adapter_dir=adapter_dir,
        files=files,
        dataset_release=dataset_release,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode()
    with tarfile.open(output, "w:gz", format=tarfile.PAX_FORMAT) as archive:
        info = tarfile.TarInfo("release.json")
        info.size = len(manifest_bytes)
        info.mode = 0o600
        info.mtime = 0
        archive.addfile(info, io.BytesIO(manifest_bytes))
        evaluation_info = tarfile.TarInfo("evaluation-summary.json")
        evaluation_info.size = len(evaluation_bytes)
        evaluation_info.mode = 0o600
        evaluation_info.mtime = 0
        archive.addfile(evaluation_info, io.BytesIO(evaluation_bytes))
        approval_info = tarfile.TarInfo("promotion-approval.json")
        approval_info.size = len(approval_bytes)
        approval_info.mode = 0o600
        approval_info.mtime = 0
        archive.addfile(approval_info, io.BytesIO(approval_bytes))
        for path in files:
            archive.add(
                path,
                arcname=f"adapter/{path.relative_to(adapter_dir).as_posix()}",
                recursive=False,
            )

    result = {
        "release_id": release_id,
        "bundle": str(output),
        "bundle_sha256": file_sha256(output),
        "size_bytes": output.stat().st_size,
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return result


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--release-id", required=True)
    cli.add_argument("--training-output", type=Path, required=True)
    cli.add_argument("--evaluation-summary", type=Path, required=True)
    cli.add_argument("--promotion-approval", type=Path, required=True)
    cli.add_argument("--dataset-release", required=True)
    cli.add_argument("--output", type=Path, required=True)
    return cli


def main() -> int:
    arguments = parser().parse_args()
    try:
        package_release(
            release_id=arguments.release_id,
            training_output=arguments.training_output,
            evaluation_summary=arguments.evaluation_summary,
            promotion_approval=arguments.promotion_approval,
            dataset_release=arguments.dataset_release,
            output=arguments.output,
        )
    except ReleaseError as error:
        print(json.dumps({"event": "error", "message": str(error)}, ensure_ascii=False))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
