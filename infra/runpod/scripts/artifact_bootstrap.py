#!/usr/bin/env python3
"""Download and safely unpack one immutable SLLM release bundle."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tarfile
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

MAX_BUNDLE_BYTES = 10 * 1024 * 1024 * 1024
RELEASE_ID = re.compile(r"[a-z0-9][a-z0-9._-]{2,63}\Z")
MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*\Z")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
RELEASE_ROOT = Path("/opt/f2-models")
EVALUATION_SUMMARY = "evaluation-summary.json"
PROMOTION_APPROVAL = "promotion-approval.json"
PROMOTION_DECISION_OWNER = "fine-tuning-owner"


class BootstrapError(RuntimeError):
    """Release download or contract failure without secret values."""


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        request: urllib.request.Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> None:
        return None


DIRECT_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}), NoRedirectHandler()
)


@dataclass(frozen=True)
class Release:
    release_id: str
    base_model_id: str
    base_model_revision: str
    adapter_path: str


def _required(source: dict[str, str], name: str) -> str:
    value = source.get(name, "").strip()
    if not value or value.startswith("{{ RUNPOD_SECRET_"):
        raise BootstrapError(f"{name} is required")
    return value


def _json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BootstrapError(f"{label} is unreadable") from error
    if not isinstance(value, dict):
        raise BootstrapError(f"{label} must be an object")
    return value


def _verify_sha256(path: Path, expected: Any, label: str) -> None:
    if not isinstance(expected, str) or SHA256.fullmatch(expected) is None:
        raise BootstrapError(f"release manifest {label} checksum is invalid")
    try:
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise BootstrapError(f"{label} is unreadable") from error
    if actual != expected:
        raise BootstrapError(f"{label} checksum does not match the release manifest")


def _download(url: str, expected_sha256: str, output: Path) -> None:
    request = urllib.request.Request(url, headers={"Accept": "application/gzip"})
    digest = hashlib.sha256()
    received = 0
    try:
        with (
            DIRECT_OPENER.open(request, timeout=60) as response,
            output.open("wb") as file,
        ):
            while chunk := response.read(1024 * 1024):
                received += len(chunk)
                if received > MAX_BUNDLE_BYTES:
                    raise BootstrapError("SLLM release bundle exceeds 10 GiB")
                digest.update(chunk)
                file.write(chunk)
    except (OSError, urllib.error.URLError) as error:
        raise BootstrapError("could not download the SLLM release bundle") from error
    if digest.hexdigest() != expected_sha256:
        raise BootstrapError("SLLM release bundle checksum mismatch")


def _safe_members(archive: tarfile.TarFile) -> list[tarfile.TarInfo]:
    members = archive.getmembers()
    names = [member.name for member in members]
    if len(names) != len(set(names)):
        raise BootstrapError("release bundle contains duplicate paths")
    for member in members:
        path = PurePosixPath(member.name)
        if (
            not member.isfile()
            or path.is_absolute()
            or ".." in path.parts
            or member.issym()
            or member.islnk()
        ):
            raise BootstrapError("release bundle contains an unsafe member")
        if member.name not in {
            "release.json",
            EVALUATION_SUMMARY,
            PROMOTION_APPROVAL,
        } and not member.name.startswith("adapter/"):
            raise BootstrapError("release bundle contains an unapproved member")
    return members


def _extract(archive_path: Path, destination: Path) -> dict[str, Any]:
    try:
        archive = tarfile.open(archive_path, "r:gz")  # noqa: SIM115
    except (OSError, tarfile.TarError) as error:
        raise BootstrapError("SLLM release bundle is not a valid tar.gz") from error
    with archive:
        members = _safe_members(archive)
        by_name = {member.name: member for member in members}
        if "release.json" not in by_name:
            raise BootstrapError("release bundle is missing release.json")
        release_file = archive.extractfile(by_name["release.json"])
        if release_file is None:
            raise BootstrapError("release.json is unreadable")
        try:
            manifest = json.load(release_file)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise BootstrapError("release.json is invalid") from error
        if not isinstance(manifest, dict):
            raise BootstrapError("release.json must be an object")
        destination.mkdir(mode=0o700, parents=True, exist_ok=False)
        for member in members:
            target = destination / member.name
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise BootstrapError("release member is unreadable")
            with target.open("xb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
            target.chmod(0o600)
    return manifest


def _validate(
    manifest: dict[str, Any], expected_release_id: str, destination: Path
) -> Release:
    if (
        manifest.get("schema_version") != 1
        or manifest.get("release_id") != expected_release_id
        or manifest.get("capability") != "f2-consultation-analysis"
        or manifest.get("served_model_name") != "sllm"
    ):
        raise BootstrapError(
            "release manifest does not match the requested SLLM release"
        )
    base = manifest.get("base_model")
    if not isinstance(base, dict):
        raise BootstrapError("release manifest is missing base_model")
    model_id = base.get("id")
    revision = base.get("revision")
    if not isinstance(model_id, str) or MODEL_ID.fullmatch(model_id) is None:
        raise BootstrapError("release base model id is invalid")
    if not isinstance(revision, str) or COMMIT.fullmatch(revision) is None:
        raise BootstrapError("release base model revision is invalid")

    evaluation = manifest.get("evaluation")
    if not isinstance(evaluation, dict):
        raise BootstrapError("release manifest is missing evaluation")
    if (
        evaluation.get("task") != "full"
        or evaluation.get("summary_path") != EVALUATION_SUMMARY
        or evaluation.get("approval_path") != PROMOTION_APPROVAL
        or evaluation.get("promotion_status") != "approved"
    ):
        raise BootstrapError("release manifest promotion contract is invalid")
    selected_model = evaluation.get("selected_model")
    if not isinstance(selected_model, str) or not selected_model.strip():
        raise BootstrapError("release manifest selected model is invalid")

    summary_path = destination / EVALUATION_SUMMARY
    approval_path = destination / PROMOTION_APPROVAL
    _verify_sha256(summary_path, evaluation.get("summary_sha256"), "evaluation summary")
    _verify_sha256(approval_path, evaluation.get("approval_sha256"), "promotion approval")
    summary = _json_object(summary_path, "evaluation summary")
    approval = _json_object(approval_path, "promotion approval")
    if summary.get("task") != "full":
        raise BootstrapError("evaluation summary is not a full-task result")
    evaluation_run_id = summary.get("run_id")
    models = summary.get("models")
    labels = (
        [model.get("label") for model in models if isinstance(model, dict)]
        if isinstance(models, list)
        else []
    )
    if (
        not isinstance(evaluation_run_id, str)
        or not evaluation_run_id.strip()
        or selected_model not in labels
    ):
        raise BootstrapError("evaluation summary does not match the promoted model")
    if (
        approval.get("schema_version") != 1
        or approval.get("status") != "approved"
        or approval.get("evaluation_run_id") != evaluation_run_id
        or approval.get("selected_model") != selected_model
        or approval.get("decision_owner") != PROMOTION_DECISION_OWNER
        or not isinstance(approval.get("rationale"), str)
        or not approval["rationale"].strip()
    ):
        raise BootstrapError("promotion approval does not match the release manifest")

    adapter = destination / "adapter"
    if (
        not adapter.is_dir()
        or not (adapter / "adapter_config.json").is_file()
        or not (adapter / "adapter_model.safetensors").is_file()
    ):
        raise BootstrapError("release adapter is incomplete")
    return Release(expected_release_id, model_id, revision, str(adapter))


def bootstrap(environment: dict[str, str] | None = None) -> Release:
    source = dict(os.environ if environment is None else environment)
    release_id = _required(source, "F2_SLLM_RELEASE_ID")
    expected_sha256 = _required(source, "F2_SLLM_BUNDLE_SHA256")
    url = _required(source, "F2_SLLM_BUNDLE_URL")
    if (
        RELEASE_ID.fullmatch(release_id) is None
        or SHA256.fullmatch(expected_sha256) is None
    ):
        raise BootstrapError("SLLM release id or checksum is invalid")
    destination = RELEASE_ROOT / release_id
    if destination.exists():
        try:
            manifest = json.loads((destination / "release.json").read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise BootstrapError("cached release manifest is invalid") from error
        return _validate(manifest, release_id, destination)
    RELEASE_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=RELEASE_ROOT) as temporary:
        archive_path = Path(temporary) / "bundle.tar.gz"
        stage = Path(temporary) / "release"
        _download(url, expected_sha256, archive_path)
        manifest = _extract(archive_path, stage)
        release = _validate(manifest, release_id, stage)
        stage.rename(destination)
    return Release(
        release_id,
        release.base_model_id,
        release.base_model_revision,
        str(destination / "adapter"),
    )
