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
from collections.abc import Callable, Sequence
from dataclasses import dataclass
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
    required = {
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
    if set(payload) != required:
        raise ToolError("release.json has an invalid top-level schema")
    if payload["schema_version"] != 1:
        raise ToolError("unsupported SLLM release schema")
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
    adapter = payload["adapter"]
    if (
        not isinstance(adapter, dict)
        or adapter.get("format") != "peft-lora"
        or adapter.get("path") != "adapter"
    ):
        raise ToolError("adapter schema is invalid")
    if (
        not isinstance(adapter.get("sha256"), str)
        or SHA256.fullmatch(adapter["sha256"]) is None
    ):
        raise ToolError("adapter hash is invalid")
    evaluation = payload["evaluation"]
    required_evaluation = {
        "task",
        "summary_path",
        "summary_sha256",
        "promotion_status",
        "selected_model",
        "approval_path",
        "approval_sha256",
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
    if (
        approval.get("schema_version") != 1
        or approval.get("status") != "approved"
        or approval.get("evaluation_run_id") != run_id
        or approval.get("selected_model") != selected_model
        or approval.get("decision_owner") != PROMOTION_DECISION_OWNER
        or not isinstance(approval.get("rationale"), str)
        or not approval["rationale"].strip()
    ):
        raise ToolError("promotion approval does not match release.json")


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
        if {
            "release.json",
            EVALUATION_SUMMARY,
            PROMOTION_APPROVAL,
        } - by_name.keys():
            raise ToolError("bundle is missing approved release metadata")
        adapter_names = [name for name in names if name.startswith("adapter/")]
        required = {"adapter/adapter_config.json", "adapter/adapter_model.safetensors"}
        if not required.issubset(adapter_names):
            raise ToolError("bundle is missing required PEFT adapter files")
        manifest_bytes = _member_bytes(archive, by_name["release.json"])
        manifest = _validate_manifest(_json_object(manifest_bytes, "release.json"))
        evaluation_bytes = _member_bytes(archive, by_name[EVALUATION_SUMMARY])
        approval_bytes = _member_bytes(archive, by_name[PROMOTION_APPROVAL])
        _validate_promotion_contract(manifest, evaluation_bytes, approval_bytes)
        adapter_members = [by_name[name] for name in adapter_names]
        adapter_sha256, adapter_size = _archive_tree_sha256(archive, adapter_members)
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
        self, *, bucket: str, key: str, body: Path, content_type: str, sha256: str
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
            f"sha256={sha256}",
        )

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
    client.put_immutable(
        bucket=bucket,
        key=f"{prefix}/bundle.tar.gz",
        body=bundle.path,
        content_type="application/gzip",
        sha256=bundle.sha256,
    )
    with tempfile.NamedTemporaryFile("wb", suffix=".json") as file:
        file.write(bundle.manifest_bytes)
        file.flush()
        client.put_immutable(
            bucket=bucket,
            key=f"{prefix}/release.json",
            body=Path(file.name),
            content_type="application/json",
            sha256=hashlib.sha256(bundle.manifest_bytes).hexdigest(),
        )
    emit(
        "sllm-publish-complete",
        bucket=bucket,
        prefix=prefix,
        release_id=bundle.release_id,
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
