"""Shared desired state; selecting never starts resources or changes DB models."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from uuid import uuid4

from manage_dev_power import ToolError, emit
from selection_catalog import (
    Cloud,
    Workload,
    default_hardware,
    hardware_options,
    normalize_spec,
    validation_metadata,
)

WORKLOADS = tuple(item.value for item in Workload)


def fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def document(raw: dict) -> dict:
    """Read legacy without writing; preserve explicit choices and give it a stable ID."""
    if not isinstance(raw, dict) or set(raw) - {
        *WORKLOADS,
        "schema_version",
        "selection_id",
        "updated_at",
        "updated_by",
    }:
        raise ToolError("unsupported serving selection document")
    if not set(WORKLOADS).issubset(raw) or raw.get("schema_version", 1) not in (1, 2):
        raise ToolError("serving selection must contain f2 and general")
    result = {
        name: normalize_spec(name, raw[name]) if raw[name] else None
        for name in WORKLOADS
    }
    result.update(
        schema_version=2,
        selection_id=raw.get("selection_id", "legacy-" + fingerprint(raw)),
        updated_at=raw.get("updated_at"),
        updated_by=raw.get("updated_by"),
    )
    return result


def require_stopped(serving) -> None:
    serving.no_deployment()
    group = serving.power.describe_asg()
    if group.get("DesiredCapacity", 0) or group.get("Instances"):
        raise ToolError("ai-select requires dev-stop: app/Worker host must be stopped")
    for name in WORKLOADS:
        if serving.endpoint(name).get("status") != "offline":
            raise ToolError("ai-select requires both endpoints offline; run dev-stop")
        if any(i["State"]["Name"] != "stopped" for i in serving.instances(name)):
            raise ToolError("ai-select requires all managed AWS GPUs stopped")
    if serving.managed_pods():
        raise ToolError("ai-select requires managed RunPod Pods deleted; run dev-stop")


def confirm(message: str) -> None:
    if not sys.stdin.isatty() or input(message + " [yes/N]: ").strip().lower() != "yes":
        raise ToolError("confirmation not supplied; no further changes applied")


def choose(label: str, values: list[str], default: str | None = None) -> str:
    if not sys.stdin.isatty():
        raise ToolError("interactive selection requires a TTY; use explicit options")
    for index, value in enumerate(values, 1):
        print(f"{index}. {value}" + (" (current/default)" if value == default else ""))
    value = input(f"{label}: ").strip()
    if not value and default in values:
        return default
    if value.isdigit() and 1 <= int(value) <= len(values):
        return values[int(value) - 1]
    if value in values:
        return value
    raise ToolError("choose one of the listed values")


def save(serving, changes: dict, *, apply: bool, interactive: bool = False) -> dict:
    require_stopped(serving)
    before = serving.selection_document()
    after = dict(before)
    for workload, spec in changes.items():
        after[workload] = normalize_spec(workload, spec)
        if workload == "f2":
            # Validate the private S3 manifest and catalog cross-hashes before selection.
            serving.validate_release(after[workload])
        emit(
            "ai-select-preview",
            workload=workload,
            before=before[workload],
            after=after[workload],
            validation=validation_metadata(workload, after[workload]),
        )
    if not apply:
        emit("ai-select-preview-only", next="repeat with --apply to save")
        return after
    if interactive:
        confirm("Save this shared dev selection (no startup/DB change)?")
    require_stopped(serving)
    if fingerprint(serving.selection_document()) != fingerprint(before):
        raise ToolError("shared selection changed; review again")
    if all(before[name] == after[name] for name in WORKLOADS) and not before[
        "selection_id"
    ].startswith("legacy-"):
        emit("ai-select-unchanged", selection_id=before["selection_id"])
        return before
    after.update(
        selection_id=str(uuid4()),
        updated_at=datetime.now(UTC).isoformat(),
        updated_by=serving.session.client("sts").get_caller_identity()["Arn"],
    )
    serving.write("serving/SELECTION", after)
    emit(
        "ai-select-saved",
        selection_id=after["selection_id"],
        next="dev-start (first deployment: dev-prepare-app)",
    )
    return after


def select(serving, args) -> None:
    before = serving.selection()
    interactive = args.workload is None
    workload = args.workload or choose("Workload", list(WORKLOADS), "f2")
    previous = before[workload] or {}
    cloud = args.cloud or (
        choose("Cloud", [c.value for c in Cloud], previous.get("cloud", "runpod"))
        if interactive
        else previous.get("cloud")
    )
    if not cloud:
        raise ToolError("--cloud is required for the first explicit selection")
    hardware = args.hardware_profile or (
        choose(
            "Hardware profile",
            [str(x) for x in hardware_options(workload, cloud)],
            previous.get("hardware_profile")
            if previous.get("cloud") == cloud
            else str(default_hardware(workload, cloud)),
        )
        if interactive
        else (
            previous.get("hardware_profile")
            if previous.get("cloud") == cloud
            else str(default_hardware(workload, cloud))
        )
    )
    spec = {"cloud": cloud, "hardware_profile": hardware}
    if workload == "general":
        from model_profiles import GeneralModelProfile

        # The model catalog owns the available model IDs.
        profiles = [p.value for p in GeneralModelProfile]
        model = args.model_profile or (
            choose(
                "Model profile",
                profiles,
                previous.get("model_profile", "qwen38-27b-fp8"),
            )
            if interactive
            else previous.get("model_profile", "qwen38-27b-fp8")
        )
        if args.release or args.bucket or args.allow_dev_release:
            raise ToolError("release/bucket options are only valid for F2")
        spec["model_profile"] = model
    else:
        from pathlib import Path

        catalog = json.loads(
            (Path(__file__).resolve().parents[1] / "runpod/releases.json").read_text()
        )["releases"]
        release = args.release or (
            choose(
                "Release",
                [r["release_id"] for r in catalog],
                previous.get("release_id", "consultation-v3"),
            )
            if interactive
            else previous.get("release_id")
        )
        if args.model_profile:
            raise ToolError("--model-profile is only valid for general")
        spec.update(
            release_id=release,
            bucket=args.bucket
            or previous.get("bucket")
            or f"{serving.prefix}-data-model-apse2-{serving.settings.account_id}",
            allow_dev_release=args.allow_dev_release
            or (
                previous.get("allow_dev_release", False)
                if release == previous.get("release_id")
                else False
            ),
        )
    save(
        serving,
        {workload: spec},
        apply=args.apply or interactive,
        interactive=interactive,
    )
