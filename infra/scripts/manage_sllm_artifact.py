#!/usr/bin/env python3
"""Inspect and publish immutable SLLM release bundles to the private model bucket."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

CAPABILITY = "f2-consultation-analysis"
SERVED_MODEL_NAME = "sllm"
RELEASE_ID = re.compile(r"[a-z0-9][a-z0-9._-]{2,63}\Z")
MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*\Z")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
MAX_BUNDLE_BYTES = 10 * 1024 * 1024 * 1024
EVALUATION_SUMMARY = "evaluation-summary.json"
PROMOTION_APPROVAL = "promotion-approval.json"
PROMOTION_DECISION_OWNER = "fine-tuning-owner"
RELEASE_MODES = {"lora", "base"}
RELEASE_STAGES = {"verified", "dev"}
V2_ADAPTER_FILES = {
    "adapter/README.md",
    "adapter/adapter_config.json",
    "adapter/adapter_model.safetensors",
    "adapter/added_tokens.json",
    "adapter/chat_template.jinja",
    "adapter/generation_config.json",
    "adapter/merges.txt",
    "adapter/special_tokens_map.json",
    "adapter/tokenizer.json",
    "adapter/tokenizer.model",
    "adapter/tokenizer_config.json",
    "adapter/vocab.json",
}


class ToolError(RuntimeError):
    """An expected failure safe to show to an operator."""


def emit(event: str, **fields: object) -> None:
    print(json.dumps({"event": event, **fields}, ensure_ascii=False, sort_keys=True))


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _member_bytes(
    archive: tarfile.TarFile, member: tarfile.TarInfo, *, limit: int = 2 * 1024 * 1024
) -> bytes:
    if member.size > limit:
        raise ToolError(f"bundle metadata member is too large: {member.name}")
    file = archive.extractfile(member)
    if file is None:
        raise ToolError(f"bundle member is unreadable: {member.name}")
    return file.read()


def _json_object(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ToolError(f"{label} is not valid UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise ToolError(f"{label} must contain a JSON object")
    return value


def _tree_sha256(adapter_members: list[tuple[str, bytes]]) -> str:
    digest = hashlib.sha256()
    for relative, content in sorted(adapter_members):
        encoded = relative.encode()
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
        digest.update(hashlib.sha256(content).digest())
    return digest.hexdigest()


def _archive_tree_sha256(
    archive: tarfile.TarFile, members: list[tarfile.TarInfo]
) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    for member in sorted(members, key=lambda item: item.name):
        relative = member.name.removeprefix("adapter/").encode()
        content_digest = hashlib.sha256()
        source = archive.extractfile(member)
        if source is None:
            raise ToolError(f"bundle member is unreadable: {member.name}")
        while chunk := source.read(1024 * 1024):
            total += len(chunk)
            content_digest.update(chunk)
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(content_digest.digest())
    return digest.hexdigest(), total


def _validate_manifest(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ToolError("release.json must contain a JSON object")
    common = {
        "schema_version",
        "release_id",
        "capability",
        "served_model_name",
        "created_at",
        "base_model",
        "adapter",
        "training",
        "evaluation",
    }
    schema_version = payload.get("schema_version")
    required = common if schema_version == 1 else common | {"release_mode"}
    allowed = required if schema_version != 2 else required | {"release_stage"}
    if (
        schema_version not in {1, 2}
        or not required.issubset(payload)
        or set(payload) - allowed
    ):
        raise ToolError("release.json has an invalid top-level schema")
    if (
        not isinstance(payload["release_id"], str)
        or RELEASE_ID.fullmatch(payload["release_id"]) is None
    ):
        raise ToolError("release_id is invalid")
    if (
        payload["capability"] != CAPABILITY
        or payload["served_model_name"] != SERVED_MODEL_NAME
    ):
        raise ToolError("release capability or served model name is invalid")
    try:
        created_at = datetime.fromisoformat(
            str(payload["created_at"]).replace("Z", "+00:00")
        )
    except ValueError as error:
        raise ToolError("release created_at must be an offset timestamp") from error
    if created_at.utcoffset() is None:
        raise ToolError("release created_at must be an offset timestamp")
    base = payload["base_model"]
    if not isinstance(base, dict) or set(base) != {"id", "revision"}:
        raise ToolError("base_model schema is invalid")
    if not isinstance(base["id"], str) or MODEL_ID.fullmatch(base["id"]) is None:
        raise ToolError("base model id is invalid")
    if (
        not isinstance(base["revision"], str)
        or COMMIT.fullmatch(base["revision"]) is None
    ):
        raise ToolError("base model revision must be immutable")
    release_mode = "lora" if schema_version == 1 else payload["release_mode"]
    if release_mode not in RELEASE_MODES:
        raise ToolError("release_mode must be lora or base")
    release_stage = (
        "verified" if schema_version == 1 else payload.get("release_stage", "verified")
    )
    if release_stage not in RELEASE_STAGES:
        raise ToolError("release_stage must be verified or dev")
    if release_stage == "dev" and not payload["release_id"].startswith("dev-"):
        raise ToolError("dev release_id must start with dev-")
    adapter = payload["adapter"]
    training = payload["training"]
    if release_mode == "base":
        if adapter is not None or training is not None:
            raise ToolError(
                "base release must not contain adapter or training metadata"
            )
    else:
        required_adapter = {"format", "path", "sha256", "size_bytes", "file_count"}
        if (
            not isinstance(adapter, dict)
            or set(adapter) != required_adapter
            or adapter.get("format") != "peft-lora"
            or adapter.get("path") != "adapter"
        ):
            raise ToolError("adapter schema is invalid")
        if (
            not isinstance(adapter.get("sha256"), str)
            or SHA256.fullmatch(adapter["sha256"]) is None
            or isinstance(adapter.get("size_bytes"), bool)
            or not isinstance(adapter.get("size_bytes"), int)
            or adapter["size_bytes"] < 1
            or isinstance(adapter.get("file_count"), bool)
            or not isinstance(adapter.get("file_count"), int)
            or adapter["file_count"] < 2
        ):
            raise ToolError("adapter metadata is invalid")
        expected_training = (
            {"code_revision", "dataset_release", "train_sha256", "validation_sha256"}
            if schema_version == 1
            else {"code_revision", "train_sha256", "validation_sha256"}
        )
        if not isinstance(training, dict) or set(training) != expected_training:
            raise ToolError("training metadata schema is invalid")
        for name in ("train_sha256", "validation_sha256"):
            if (
                not isinstance(training[name], str)
                or SHA256.fullmatch(training[name]) is None
            ):
                raise ToolError(f"training {name} is invalid")
        code_revision = training["code_revision"]
        if code_revision is not None and (
            not isinstance(code_revision, str)
            or COMMIT.fullmatch(code_revision) is None
        ):
            raise ToolError("training code_revision is invalid")
    evaluation = payload["evaluation"]
    if release_stage == "dev":
        if (
            not isinstance(evaluation, dict)
            or set(evaluation) != {"status", "dataset_release"}
            or evaluation.get("status") != "not-evaluated"
            or not isinstance(evaluation.get("dataset_release"), str)
            or not evaluation["dataset_release"].strip()
        ):
            raise ToolError("dev release evaluation marker is invalid")
        return payload
    required_evaluation = {
        "task",
        "summary_path",
        "summary_sha256",
        "promotion_status",
        "selected_model",
        "approval_path",
        "approval_sha256",
    }
    if schema_version == 2:
        required_evaluation |= {
            "dataset_release",
            "dataset_sha256",
            "source_summary_sha256",
        }
    if (
        not isinstance(evaluation, dict)
        or set(evaluation) != required_evaluation
        or evaluation.get("task") != "full"
        or evaluation.get("promotion_status") != "approved"
    ):
        raise ToolError("a consultation-analysis release requires full-task evaluation")
    if evaluation.get("summary_path") != EVALUATION_SUMMARY:
        raise ToolError("evaluation summary path is invalid")
    if (
        not isinstance(evaluation.get("summary_sha256"), str)
        or SHA256.fullmatch(evaluation["summary_sha256"]) is None
    ):
        raise ToolError("evaluation summary hash is invalid")
    if evaluation.get("approval_path") != PROMOTION_APPROVAL:
        raise ToolError("promotion approval path is invalid")
    if (
        not isinstance(evaluation.get("approval_sha256"), str)
        or SHA256.fullmatch(evaluation["approval_sha256"]) is None
    ):
        raise ToolError("promotion approval hash is invalid")
    if (
        not isinstance(evaluation.get("selected_model"), str)
        or not evaluation["selected_model"].strip()
    ):
        raise ToolError("promoted model is invalid")
    if schema_version == 2 and (
        not isinstance(evaluation.get("dataset_release"), str)
        or not evaluation["dataset_release"].strip()
        or not isinstance(evaluation.get("dataset_sha256"), str)
        or SHA256.fullmatch(evaluation["dataset_sha256"]) is None
        or not isinstance(evaluation.get("source_summary_sha256"), str)
        or SHA256.fullmatch(evaluation["source_summary_sha256"]) is None
    ):
        raise ToolError("evaluation dataset provenance is invalid")
    return payload


def _validate_promotion_contract(
    manifest: dict[str, Any], summary_bytes: bytes, approval_bytes: bytes
) -> None:
    evaluation = manifest["evaluation"]
    assert isinstance(evaluation, dict)
    if hashlib.sha256(summary_bytes).hexdigest() != evaluation["summary_sha256"]:
        raise ToolError("evaluation summary hash does not match release.json")
    if hashlib.sha256(approval_bytes).hexdigest() != evaluation["approval_sha256"]:
        raise ToolError("promotion approval hash does not match release.json")
    summary = _json_object(summary_bytes, "evaluation summary")
    approval = _json_object(approval_bytes, "promotion approval")
    run_id = summary.get("run_id")
    models = summary.get("models")
    labels = (
        [model.get("label") for model in models if isinstance(model, dict)]
        if isinstance(models, list)
        else []
    )
    selected_model = evaluation["selected_model"]
    if (
        summary.get("task") != "full"
        or not isinstance(run_id, str)
        or not run_id.strip()
        or selected_model not in labels
    ):
        raise ToolError("evaluation summary does not match the promoted model")
    schema_version = manifest["schema_version"]
    approval_version = 1 if schema_version == 1 else 2
    required_approval = {
        "schema_version",
        "status",
        "evaluation_run_id",
        "selected_model",
        "decision_owner",
        "rationale",
    }
    if schema_version == 2:
        required_approval.add("release_mode")
    if (
        set(approval) != required_approval
        or approval.get("schema_version") != approval_version
        or approval.get("status") != "approved"
        or approval.get("evaluation_run_id") != run_id
        or approval.get("selected_model") != selected_model
        or approval.get("decision_owner") != PROMOTION_DECISION_OWNER
        or not isinstance(approval.get("rationale"), str)
        or not approval["rationale"].strip()
    ):
        raise ToolError("promotion approval does not match release.json")
    if schema_version == 2:
        selected = next(
            (
                model
                for model in models
                if isinstance(model, dict) and model.get("label") == selected_model
            ),
            None,
        )
        if (
            summary.get("dataset_release") != evaluation["dataset_release"]
            or summary.get("dataset_sha256") != evaluation["dataset_sha256"]
            or summary.get("release_mode") != manifest["release_mode"]
            or approval.get("release_mode") != manifest["release_mode"]
            or not isinstance(selected, dict)
            or selected.get("model_id") != manifest["base_model"]["id"]
            or selected.get("resolved_model_revision")
            != manifest["base_model"]["revision"]
        ):
            raise ToolError("v2 evaluation provenance does not match release.json")
        expected_adapter_hash = (
            manifest["adapter"]["sha256"]
            if manifest["release_mode"] == "lora"
            else None
        )
        if selected.get("adapter_sha256") != expected_adapter_hash:
            raise ToolError("v2 evaluation adapter does not match release.json")


@dataclass(frozen=True)
class InspectedBundle:
    path: Path
    manifest: dict[str, Any]
    manifest_bytes: bytes
    sha256: str
    size_bytes: int

    @property
    def release_id(self) -> str:
        return str(self.manifest["release_id"])

    @property
    def release_mode(self) -> str:
        return str(self.manifest.get("release_mode", "lora"))

    @property
    def release_stage(self) -> str:
        return str(self.manifest.get("release_stage", "verified"))


def inspect_bundle(path: Path) -> InspectedBundle:
    if not path.is_file() or path.is_symlink():
        raise ToolError("bundle must be a regular local file")
    size = path.stat().st_size
    if size <= 0 or size > MAX_BUNDLE_BYTES:
        raise ToolError("bundle size must be between 1 byte and 10 GiB")
    try:
        archive = tarfile.open(path, "r:gz")  # noqa: SIM115
    except (OSError, tarfile.TarError) as error:
        raise ToolError("bundle must be a readable tar.gz archive") from error
    with archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        if len(names) != len(set(names)):
            raise ToolError("bundle contains duplicate member names")
        for member in members:
            pure = PurePosixPath(member.name)
            if (
                pure.is_absolute()
                or ".." in pure.parts
                or member.issym()
                or member.islnk()
            ):
                raise ToolError("bundle contains an unsafe path or link")
            if not member.isfile():
                raise ToolError("bundle may contain regular files only")
            if member.name not in {
                "release.json",
                EVALUATION_SUMMARY,
                PROMOTION_APPROVAL,
            } and not member.name.startswith("adapter/"):
                raise ToolError(f"bundle contains an unapproved file: {member.name}")
        by_name = {member.name: member for member in members}
        if "release.json" not in by_name:
            raise ToolError("bundle is missing release.json")
        manifest_bytes = _member_bytes(archive, by_name["release.json"])
        manifest = _validate_manifest(_json_object(manifest_bytes, "release.json"))
        release_mode = str(manifest.get("release_mode", "lora"))
        release_stage = str(manifest.get("release_stage", "verified"))
        promotion_names = {EVALUATION_SUMMARY, PROMOTION_APPROVAL}
        if release_stage == "verified" and promotion_names - by_name.keys():
            raise ToolError("bundle is missing approved release metadata")
        if release_stage == "dev" and promotion_names & by_name.keys():
            raise ToolError(
                "dev bundle must not contain evaluation or approval metadata"
            )
        adapter_names = [name for name in names if name.startswith("adapter/")]
        required = {"adapter/adapter_config.json", "adapter/adapter_model.safetensors"}
        if release_mode == "lora" and not required.issubset(adapter_names):
            raise ToolError("bundle is missing required PEFT adapter files")
        if manifest["schema_version"] == 2 and set(adapter_names) - V2_ADAPTER_FILES:
            raise ToolError("v2 bundle contains an unapproved adapter file")
        if release_mode == "base" and adapter_names:
            raise ToolError("base release bundle must not contain adapter files")
        if release_stage == "verified":
            evaluation_bytes = _member_bytes(archive, by_name[EVALUATION_SUMMARY])
            approval_bytes = _member_bytes(archive, by_name[PROMOTION_APPROVAL])
            _validate_promotion_contract(manifest, evaluation_bytes, approval_bytes)
        if release_mode == "lora":
            adapter_members = [by_name[name] for name in adapter_names]
            adapter_sha256, adapter_size = _archive_tree_sha256(
                archive, adapter_members
            )
            if adapter_sha256 != manifest["adapter"]["sha256"]:
                raise ToolError("adapter hash does not match release.json")
            if adapter_size != manifest["adapter"].get("size_bytes"):
                raise ToolError("adapter size does not match release.json")
            if len(adapter_members) != manifest["adapter"].get("file_count"):
                raise ToolError("adapter file count does not match release.json")
    return InspectedBundle(path, manifest, manifest_bytes, file_sha256(path), size)


CommandExecutor = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def execute(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, capture_output=True, text=True)


class AwsCli:
    def __init__(
        self,
        executor: CommandExecutor = execute,
        *,
        profile: str = "",
        region: str = "ap-northeast-2",
    ) -> None:
        self.executor = executor
        self.profile = profile
        self.region = region

    def run(self, *arguments: str) -> str:
        command = ["aws", *arguments, "--region", self.region]
        if self.profile:
            command.extend(["--profile", self.profile])
        result = self.executor(command)
        if result.returncode != 0:
            raise ToolError(f"AWS CLI operation failed: {' '.join(arguments[:2])}")
        return result.stdout.strip()

    def put_immutable(
        self,
        *,
        bucket: str,
        key: str,
        body: Path,
        content_type: str,
        metadata: Mapping[str, str],
    ) -> None:
        self.run(
            "s3api",
            "put-object",
            "--bucket",
            bucket,
            "--key",
            key,
            "--body",
            str(body),
            "--content-type",
            content_type,
            "--server-side-encryption",
            "AES256",
            "--if-none-match",
            "*",
            "--metadata",
            ",".join(f"{name}={value}" for name, value in sorted(metadata.items())),
        )

    def object_head(self, *, bucket: str, key: str) -> dict[str, Any] | None:
        listed = self.run(
            "s3api",
            "list-objects-v2",
            "--bucket",
            bucket,
            "--prefix",
            key,
            "--max-keys",
            "2",
            "--output",
            "json",
        )
        try:
            entries = json.loads(listed).get("Contents", [])
        except (AttributeError, json.JSONDecodeError) as error:
            raise ToolError("AWS CLI returned invalid S3 object listing") from error
        if not any(
            isinstance(item, dict) and item.get("Key") == key for item in entries
        ):
            return None
        try:
            head = json.loads(
                self.run(
                    "s3api",
                    "head-object",
                    "--bucket",
                    bucket,
                    "--key",
                    key,
                    "--output",
                    "json",
                )
            )
        except json.JSONDecodeError as error:
            raise ToolError("AWS CLI returned invalid S3 object metadata") from error
        if not isinstance(head, dict):
            raise ToolError("AWS CLI returned invalid S3 object metadata")
        return head

    def ensure_immutable(
        self,
        *,
        bucket: str,
        key: str,
        body: Path,
        content_type: str,
        metadata: Mapping[str, str],
    ) -> str:
        existing = self.object_head(bucket=bucket, key=key)
        if existing is not None:
            actual = existing.get("Metadata")
            if not isinstance(actual, dict) or actual != dict(metadata):
                raise ToolError(f"immutable SLLM release object already differs: {key}")
            return "retained-identical"
        self.put_immutable(
            bucket=bucket,
            key=key,
            body=body,
            content_type=content_type,
            metadata=metadata,
        )
        verified = self.object_head(bucket=bucket, key=key)
        actual = verified.get("Metadata") if isinstance(verified, dict) else None
        if not isinstance(actual, dict) or actual != dict(metadata):
            raise ToolError(
                f"published SLLM release object could not be verified: {key}"
            )
        return "created"

    def presign(self, *, bucket: str, key: str, expires: int) -> str:
        return self.run(
            "s3", "presign", f"s3://{bucket}/{key}", "--expires-in", str(expires)
        )


def release_prefix(release_id: str) -> str:
    return f"releases/sllm/{release_id}"


def publish(
    bundle: InspectedBundle, *, bucket: str, client: AwsCli, apply: bool
) -> None:
    prefix = release_prefix(bundle.release_id)
    emit(
        "sllm-publish-plan",
        bucket=bucket,
        prefix=prefix,
        bundle_sha256=bundle.sha256,
        size_bytes=bundle.size_bytes,
        apply=apply,
    )
    if not apply:
        return
    manifest_sha256 = hashlib.sha256(bundle.manifest_bytes).hexdigest()
    is_v2 = bundle.manifest["schema_version"] == 2
    bundle_metadata = {"sha256": bundle.sha256}
    manifest_metadata = {"sha256": manifest_sha256}
    if is_v2:
        bundle_metadata["release-manifest-sha256"] = manifest_sha256
        manifest_metadata["bundle-sha256"] = bundle.sha256
    bundle_state = client.ensure_immutable(
        bucket=bucket,
        key=f"{prefix}/bundle.tar.gz",
        body=bundle.path,
        content_type="application/gzip",
        metadata=bundle_metadata,
    )
    with tempfile.NamedTemporaryFile("wb", suffix=".json") as file:
        file.write(bundle.manifest_bytes)
        file.flush()
        manifest_state = client.ensure_immutable(
            bucket=bucket,
            key=f"{prefix}/release.json",
            body=Path(file.name),
            content_type="application/json",
            metadata=manifest_metadata,
        )
    emit(
        "sllm-publish-complete",
        bucket=bucket,
        prefix=prefix,
        release_id=bundle.release_id,
        release_mode=bundle.release_mode,
        release_stage=bundle.release_stage,
        bundle_state=bundle_state,
        manifest_state=manifest_state,
    )


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--bucket", default=os.environ.get("SLLM_MODEL_BUCKET", ""))
    cli.add_argument(
        "--profile", default=os.environ.get("AWS_PROFILE", "skn30-session")
    )
    cli.add_argument("--region", default=os.environ.get("AWS_REGION", "ap-northeast-2"))
    commands = cli.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect")
    inspect.add_argument("bundle", type=Path)
    publish_parser = commands.add_parser("publish")
    publish_parser.add_argument("bundle", type=Path)
    publish_parser.add_argument("--apply", action="store_true")
    presign = commands.add_parser("presign")
    presign.add_argument("bundle", type=Path)
    presign.add_argument("--expires", type=int, default=3600)
    return cli


def main() -> int:
    arguments = parser().parse_args()
    try:
        bundle = inspect_bundle(arguments.bundle)
        if arguments.command == "inspect":
            emit(
                "sllm-bundle-valid",
                release_id=bundle.release_id,
                release_mode=bundle.release_mode,
                release_stage=bundle.release_stage,
                base_model=bundle.manifest["base_model"],
                bundle_sha256=bundle.sha256,
                size_bytes=bundle.size_bytes,
            )
            return 0
        if not arguments.bucket:
            raise ToolError("--bucket or SLLM_MODEL_BUCKET is required")
        client = AwsCli(profile=arguments.profile, region=arguments.region)
        if arguments.command == "publish":
            publish(
                bundle, bucket=arguments.bucket, client=client, apply=arguments.apply
            )
        else:
            if not 60 <= arguments.expires <= 3600:
                raise ToolError("--expires must be between 60 and 3600 seconds")
            url = client.presign(
                bucket=arguments.bucket,
                key=f"{release_prefix(bundle.release_id)}/bundle.tar.gz",
                expires=arguments.expires,
            )
            print(url)
        return 0
    except ToolError as error:
        emit("error", message=str(error))
        return 2


if __name__ == "__main__":
    sys.exit(main())
