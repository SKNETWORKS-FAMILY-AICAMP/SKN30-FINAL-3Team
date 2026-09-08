#!/usr/bin/env python3
"""EC2 host setup; credentials are read on the host and never passed in commands."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from model_profiles import load_profile

ROOT = Path("/opt/brokerage-gpu")
DATA = Path("/srv/brokerage-gpu")


def run(*args: str, data: str | None = None) -> str:
    result = subprocess.run(
        args, input=data, text=True, capture_output=True, check=False
    )
    if result.returncode:
        raise RuntimeError(f"{args[0]} operation failed; inspect host configuration")
    return result.stdout.strip()


def aws(*args: str) -> dict:
    return json.loads(
        run("aws", *args, "--region", "ap-northeast-2", "--output", "json")
    )


def write_private(path: Path, value: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "w") as output:
        output.write(value)


def main() -> None:
    config = json.loads((ROOT / "config.json").read_text())
    workload = config["workload"]
    prefix = config["prefix"]
    selection = json.loads(
        aws("ssm", "get-parameter", "--name", f"/{prefix}/serving/SELECTION")[
            "Parameter"
        ]["Value"]
    )
    selected = selection.get(workload)
    # A retained standby never boots inference without explicit preparation.
    if (not selected or selected["cloud"] != "aws") and not (
        ROOT / "prepare-candidate"
    ).exists():
        return
    selected = selected or {}
    candidate = ROOT / "candidate.json"
    if candidate.exists():
        selected = json.loads(candidate.read_text())
    image = config["image"]
    DATA.mkdir(mode=0o700, parents=True, exist_ok=True)
    (DATA / "models").mkdir(exist_ok=True)
    (DATA / "cache").mkdir(exist_ok=True)
    keys = json.loads(
        aws(
            "secretsmanager",
            "get-secret-value",
            "--secret-id",
            f"/{prefix}/ai/provider-api-keys",
        )["SecretString"]
    )
    registry = json.loads(
        aws(
            "secretsmanager",
            "get-secret-value",
            "--secret-id",
            f"/{prefix}/runpod/ghcr-registry",
        )["SecretString"]
    )
    run(
        "docker",
        "login",
        "ghcr.io",
        "--username",
        registry["username"],
        "--password-stdin",
        data=registry["token"],
    )
    try:
        run("docker", "pull", image)
    finally:
        run("docker", "logout", "ghcr.io")
    environment = {
        "HF_HOME": "/cache/huggingface",
        "VLLM_NO_USAGE_STATS": "1",
        "XDG_CACHE_HOME": "/cache",
        "VLLM_CACHE_ROOT": "/cache/vllm",
        "TORCHINDUCTOR_CACHE_DIR": "/cache/torchinductor",
        "TRITON_CACHE_DIR": "/cache/triton",
        "CUDA_CACHE_PATH": "/cache/cuda",
    }
    mounts = [f"{DATA}/models:/models:ro", f"{DATA}/cache:/cache"]
    if workload == "general":
        profile_name = selected.get("model_profile", "qwen38-27b-bnb")
        profile = load_profile(profile_name)
        models = [
            {
                "model": profile["model"],
                "revision": profile["revision"],
                "weights": profile["weights"],
                "path": "/models/general",
            }
        ]
        environment.update(
            AI_GENERAL_API_KEY=keys["AI_GENERAL_API_KEY"],
            GENERAL_MODEL_PATH="/models/general",
            GENERAL_MODEL_PROFILE=profile_name,
            VLLM_ENABLE_CUDA_COMPATIBILITY="1",
        )
        ports = ["8000:8000"]
    else:
        # Candidate release is supplied by the operator in non-secret local metadata.
        if selected["bucket"] != config["model_bucket"]:
            raise ValueError("release bucket does not match managed host configuration")
        release_id = selected["release_id"]
        manifest_key = f"releases/sllm/{release_id}/release.json"
        manifest_path = DATA / "release.json"
        aws(
            "s3api",
            "get-object",
            "--bucket",
            config["model_bucket"],
            "--key",
            manifest_key,
            str(manifest_path),
        )
        manifest = json.loads(manifest_path.read_text())
        bundle_key = f"releases/sllm/{release_id}/bundle.tar.gz"
        head = aws(
            "s3api",
            "head-object",
            "--bucket",
            config["model_bucket"],
            "--key",
            bundle_key,
        )
        url = run(
            "aws",
            "s3",
            "presign",
            f"s3://{config['model_bucket']}/{bundle_key}",
            "--expires-in",
            "3600",
            "--region",
            "ap-northeast-2",
        )
        base = manifest["base_model"]
        models = [
            {"model": base["id"], "revision": base["revision"], "path": "/models/sllm"},
            {
                "model": "openai/whisper-large-v3-turbo",
                "revision": "41f01f3fe87f28c78e2fbf8b568835947dd65ed9",
                "path": "/models/stt",
            },
        ]
        environment.update(
            {k: keys[k] for k in ("AI_VLLM_SLLM_API_KEY", "AI_VLLM_STT_API_KEY")}
        )
        environment.update(
            F2_SLLM_RELEASE_ID=release_id,
            F2_SLLM_BUNDLE_SHA256=head["Metadata"]["sha256"],
            F2_SLLM_BUNDLE_URL=url,
            F2_STT_MODEL_ID=models[1]["model"],
            F2_STT_MODEL_REVISION=models[1]["revision"],
            F2_LOCAL_MODELS="1",
        )
        # Existing release bootstrap validates bytes and adapter contents in a one-shot container.
        (DATA / "releases").mkdir(exist_ok=True)
        write_private(
            ROOT / "bootstrap.env",
            "\n".join(f"{k}={v}" for k, v in environment.items()) + "\n",
        )
        try:
            run(
                "docker",
                "run",
                "--rm",
                "--env-file",
                str(ROOT / "bootstrap.env"),
                "-v",
                f"{DATA}/releases:/opt/f2-models",
                "--entrypoint",
                "python",
                image,
                "-c",
                "import sys; sys.path.insert(0, '/opt/f2-runtime/scripts'); from artifact_bootstrap import bootstrap; bootstrap()",
            )
        finally:
            (ROOT / "bootstrap.env").unlink(missing_ok=True)
        environment.pop("F2_SLLM_BUNDLE_URL")
        mounts.append(f"{DATA}/releases:/opt/f2-models:ro")
        ports = ["8001:8001", "8002:8002"]
    (ROOT / "models.json").write_text(json.dumps(models))
    run(
        "docker",
        "run",
        "--rm",
        "-v",
        f"{DATA}/models:/models",
        "-v",
        f"{ROOT}/download_models.py:/setup/download_models.py:ro",
        "-v",
        f"{ROOT}/models.json:/setup/models.json:ro",
        "--entrypoint",
        "python3",
        image,
        "/setup/download_models.py",
        "/setup/models.json",
    )
    write_private(
        ROOT / "runtime.env",
        "\n".join(f"{k}={v}" for k, v in environment.items()) + "\n",
    )
    compose = {
        "services": {
            "model": {
                "image": image,
                "env_file": [str(ROOT / "runtime.env")],
                "volumes": mounts,
                "ports": ports,
                "shm_size": "8gb",
                "restart": "no",
                "logging": {
                    "driver": "local",
                    "options": {"max-size": "10m", "max-file": "3"},
                },
                "deploy": {
                    "resources": {
                        "reservations": {
                            "devices": [
                                {
                                    "driver": "nvidia",
                                    "count": 1,
                                    "capabilities": ["gpu"],
                                }
                            ]
                        }
                    }
                },
            }
        }
    }
    (ROOT / "compose.json").write_text(json.dumps(compose))
    run(
        "docker",
        "compose",
        "-f",
        str(ROOT / "compose.json"),
        "up",
        "-d",
        "--force-recreate",
    )
    (ROOT / "prepare-candidate").unlink(missing_ok=True)
    (ROOT / "candidate.json").unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError):
        print(
            "GPU host preparation failed; no inference readiness claimed",
            file=sys.stderr,
        )
        sys.exit(1)
