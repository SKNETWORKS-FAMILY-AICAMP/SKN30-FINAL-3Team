"""Shared dev selection catalog. It never reads credentials or changes resources."""

from __future__ import annotations

import json
import re
from enum import Enum
from pathlib import Path

from model_profiles import GeneralModelProfile, load_profile

ROOT = Path(__file__).resolve().parent
CATALOG_FILE = ROOT / "hardware-profiles.json"


class Workload(str, Enum):
    F2 = "f2"
    GENERAL = "general"


class Cloud(str, Enum):
    RUNPOD = "runpod"
    AWS = "aws"


class HardwareProfile(str, Enum):
    RUNPOD_A5000 = "runpod-a5000-24gb"
    RUNPOD_RTX4090 = "runpod-rtx4090-24gb"
    RUNPOD_L40S = "runpod-l40s-48gb"
    AWS_G6 = "aws-g6-2xlarge"
    AWS_G6E = "aws-g6e-2xlarge"


def load_catalog() -> dict:
    catalog = json.loads(CATALOG_FILE.read_text())
    if catalog.get("schema_version") != 1:
        raise ValueError("unsupported hardware catalog schema")
    if set(catalog["profiles"]) != {item.value for item in HardwareProfile}:
        raise ValueError("hardware catalog and enum disagree")
    return catalog


def hardware_options(workload: str, cloud: str) -> dict[str, dict]:
    workload, cloud = Workload(workload).value, Cloud(cloud).value
    return {
        key: value
        for key, value in load_catalog()["profiles"].items()
        if value["cloud"] == cloud and workload in value["workloads"]
    }


def default_hardware(workload: str, cloud: str) -> str:
    return load_catalog()["defaults"][Workload(workload).value][Cloud(cloud).value]


def published_image(
    workload: str, model_profile: str | None = None, image: str | None = None
) -> str:
    workload = Workload(workload).value
    catalog = load_catalog()
    if workload == Workload.F2:
        selected = image or catalog["f2_image"]["image"]
        records = [catalog["f2_image"], *catalog["f2_image_history"]]
        if not any(record["image"] == selected for record in records):
            raise ValueError("F2 image must be published in the selection catalog")
    else:
        profile = GeneralModelProfile(model_profile).value
        entries = json.loads((ROOT / "published-images.json").read_text())["images"]
        record = next(
            (
                row
                for row in entries
                if (
                    row["image"] == image
                    if image is not None
                    else row["id"] == catalog["general_default_image_id"]
                )
            ),
            None,
        )
        if record is None:
            raise ValueError("general image must be published in the image catalog")
        status = record.get("profiles", {}).get(profile, {}).get("status")
        if status not in {"cpu_only", "startup_only", "evaluated"}:
            raise ValueError("general image/profile is absent, failed, or unsupported")
        selected = record["image"]
    if not re.fullmatch(
        r"ghcr\.io/sknetworks-family-aicamp/skn30-final-3team/(?:f2|general)-serving@sha256:[0-9a-f]{64}",
        selected,
    ):
        raise ValueError("serving image must be an immutable project image digest")
    return selected


def normalize_spec(workload: str, spec: dict) -> dict:
    """Migrate legacy GPU IDs exactly; never silently change a model or cloud.

    AWS legacy specs stored an unused RunPod GPU ID. It is deliberately dropped;
    the catalog's AWS instance profile is used when no explicit profile exists.
    An absent general model is an error, including during legacy migration.
    """
    workload = Workload(workload).value
    allowed = {"cloud", "hardware_profile", "gpu_id", "image"} | (
        {"model_profile"}
        if workload == Workload.GENERAL
        else {"release_id", "bucket", "allow_dev_release"}
    )
    if not isinstance(spec, dict) or set(spec) - allowed:
        raise ValueError("unsupported fields in workload selection")
    cloud = Cloud(spec.get("cloud")).value
    options = hardware_options(workload, cloud)
    hardware = spec.get("hardware_profile")
    gpu_id = spec.get("gpu_id")
    if not hardware and cloud == Cloud.RUNPOD and gpu_id:
        hardware = next(
            (key for key, value in options.items() if value["gpu_id"] == gpu_id), None
        )
        if hardware is None:
            raise ValueError("RunPod GPU ID is not supported for this workload")
    hardware = HardwareProfile(hardware or default_hardware(workload, cloud)).value
    if hardware not in options:
        raise ValueError("hardware profile is not supported for workload/cloud")
    chosen = options[hardware]
    if cloud == Cloud.RUNPOD and gpu_id and gpu_id != chosen["gpu_id"]:
        raise ValueError("RunPod GPU ID disagrees with hardware profile")
    compatibility = load_catalog()["compatibility"][workload]
    if chosen["vram_gb"] < compatibility["minimum_vram_gb"]:
        raise ValueError("hardware profile has insufficient catalog VRAM")
    result = {"cloud": cloud, "hardware_profile": hardware}
    if cloud == Cloud.RUNPOD:
        result["gpu_id"] = chosen["gpu_id"]
    if workload == Workload.GENERAL:
        name = GeneralModelProfile(spec.get("model_profile")).value
        if name not in compatibility["model_profiles"]:
            raise ValueError("model profile is not supported by the hardware catalog")
        load_profile(name)
        result["model_profile"] = name
    else:
        release = spec.get("release_id")
        if release not in compatibility["release_ids"]:
            raise ValueError("F2 release is not supported by the hardware catalog")
        releases = json.loads((ROOT.parent / "runpod/releases.json").read_text())[
            "releases"
        ]
        record = next((row for row in releases if row["release_id"] == release), None)
        if record is None:
            raise ValueError("F2 release must exist in the immutable release catalog")
        allow_dev = spec.get("allow_dev_release", False)
        if type(allow_dev) is not bool:
            raise ValueError("allow_dev_release must be a boolean")
        if record["release_stage"] == "dev" and not allow_dev:
            raise ValueError("development release requires explicit allow_dev_release")
        bucket = spec.get("bucket", "")
        if not isinstance(bucket, str) or not re.fullmatch(
            r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket
        ):
            raise ValueError("F2 release requires an S3 bucket name")
        result.update(release_id=release, bucket=bucket, allow_dev_release=allow_dev)
    result["image"] = published_image(
        workload, result.get("model_profile"), spec.get("image")
    )
    return result


def validation_metadata(workload: str, spec: dict) -> dict:
    """Evidence is scoped; candidate/quality results never certify deployment."""
    selected = normalize_spec(workload, spec)
    hardware = load_catalog()["profiles"][selected["hardware_profile"]]
    result = {
        "status": "pending-user-startup-check",
        "hardware_profile": selected["hardware_profile"],
        "vram_gb": hardware["vram_gb"],
        "hardware_evidence": hardware["evidence"],
        "image": selected["image"],
    }
    if workload == Workload.GENERAL:
        entries = json.loads((ROOT / "published-images.json").read_text())["images"]
        record = next(row for row in entries if row["image"] == selected["image"])
        result["image_profile_evidence"] = record["profiles"][selected["model_profile"]]
        result["model_revision"] = load_profile(selected["model_profile"])["revision"]
    else:
        result["release_id"] = selected["release_id"]
        catalog = load_catalog()
        result["image_evidence"] = next(
            record
            for record in [catalog["f2_image"], *catalog["f2_image_history"]]
            if record["image"] == selected["image"]
        )
        result["memory_budget"] = {
            "sllm_fraction": 0.65,
            "stt_fraction": 0.20,
            "meaning": "configured allocation, not measured peak VRAM",
        }
    return result
