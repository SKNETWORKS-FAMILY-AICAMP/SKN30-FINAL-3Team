"""Synthetic inference probe. Never prints credentials or model response text."""

from __future__ import annotations

import io
import json
import shutil
import threading
import time
import urllib.request
import wave

from gpu_metrics import safe_identity


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def read_status(base_url: str, key: str, model: str) -> dict:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    headers = {"Authorization": f"Bearer {key}", "User-Agent": "skn30-infra/1.0"}
    with opener.open(
        urllib.request.Request(base_url + "/models", headers=headers), timeout=10
    ) as response:
        ready = model in {item["id"] for item in json.load(response)["data"]}
    result = {"model_ready": ready, "disk_free_bytes": None}
    try:
        with opener.open(
            urllib.request.Request(
                base_url.removesuffix("/v1") + "/ops/status", headers=headers
            ),
            timeout=10,
        ) as response:
            status = json.load(response)
        free = status.get("disk_free_bytes")
        if isinstance(free, int) and free >= 0:
            result["disk_free_bytes"] = free
    except (OSError, ValueError, KeyError):
        pass  # Older F2 images remain inference-compatible without this optional route.
    return result


def probe(base_url: str, key: str, model: str, *, stt: bool = False) -> None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    headers = {"Authorization": f"Bearer {key}", "User-Agent": "skn30-infra/1.0"}
    req = urllib.request.Request(base_url + "/models", headers=headers)
    with opener.open(req, timeout=15) as response:
        ids = {entry["id"] for entry in json.load(response)["data"]}
    if model not in ids:
        raise ValueError("expected model is missing")
    if stt:
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b"\0\0" * 16000)
        boundary = "skn30syntheticprobe"
        body = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="model"\r\n\r\n{model}\r\n--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="synthetic.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode()
            + output.getvalue()
            + f"\r\n--{boundary}--\r\n".encode()
        )
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        endpoint = "/audio/transcriptions"
    else:
        schema = {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
            "additionalProperties": False,
        }
        body = json.dumps(
            {
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": "연결 확인입니다. JSON으로 ok를 true로 반환하세요.",
                    }
                ],
                "max_tokens": 128,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "health", "strict": True, "schema": schema},
                },
            }
        ).encode()
        headers["Content-Type"] = "application/json"
        endpoint = "/chat/completions"
    with opener.open(
        urllib.request.Request(base_url + endpoint, data=body, headers=headers),
        timeout=120,
    ) as response:
        result = json.load(response)
    if stt:
        if not isinstance(result.get("text"), str):
            raise ValueError("invalid transcription contract")
    elif json.loads(result["choices"][0]["message"]["content"]) != {"ok": True}:
        raise ValueError("invalid structured generation")


def read_telemetry(base_url: str, key: str) -> dict:
    """Read optional status fields from either old or new serving images."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(
            urllib.request.Request(
                base_url.removesuffix("/v1") + "/ops/status",
                headers={
                    "Authorization": f"Bearer {key}",
                    "User-Agent": "skn30-infra/1.0",
                },
            ),
            timeout=5,
        ) as response:
            document = json.load(response)
        if not isinstance(document, dict):
            return {"identity": {}, "gpu": None}
        gpu = document.get("gpu")
        if (
            not isinstance(gpu, dict)
            or gpu.get("status") != "sampled"
            or (
                type(gpu.get("used_mib")) is not int
                or type(gpu.get("total_mib")) is not int
                or not 0 <= gpu["used_mib"] <= gpu["total_mib"]
                or gpu["total_mib"] == 0
            )
        ):
            gpu = None
        else:
            gpu = {"used_mib": gpu["used_mib"], "total_mib": gpu["total_mib"]}
        return {"identity": safe_identity(document.get("identity")), "gpu": gpu}
    except (OSError, ValueError, KeyError, TypeError):
        return {"identity": {}, "gpu": None}


def verify(
    base_url: str,
    key: str,
    model: str,
    *,
    stt: bool = False,
    expected_identity: dict | None = None,
    sample_interval: float = 0.25,
) -> dict:
    """Run synthetic inference with bounded status sampling and no response text.

    Peak means the largest observed device sample during this check; it is not
    a guaranteed maximum, per-process allocation, or a hardware capacity proof.
    Missing expected identity fails verification while ordinary probe remains
    compatible with old images lacking the optional status extension.
    """
    expected = safe_identity(expected_identity or {})
    if expected != (expected_identity or {}):
        raise ValueError("expected identity contains unsupported fields or values")
    if sample_interval < 0.05 or sample_interval > 10:
        raise ValueError("sample interval must be between 0.05 and 10 seconds")
    snapshots = [read_telemetry(base_url, key)]
    done = threading.Event()

    def collect():
        while not done.wait(sample_interval):
            snapshots.append(read_telemetry(base_url, key))

    worker = threading.Thread(target=collect, daemon=True)
    worker.start()
    started = time.monotonic()
    error = None
    try:
        probe(base_url, key, model, stt=stt)
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        error = "synthetic-inference-failed"
    finally:
        elapsed = time.monotonic() - started
        done.set()
        worker.join(timeout=6)
    snapshots.append(read_telemetry(base_url, key))
    identity = snapshots[-1]["identity"]
    checks = {
        name: (
            "unavailable"
            if name not in identity
            else "match"
            if identity[name] == value
            else "mismatch"
        )
        for name, value in expected.items()
    }
    changed = any(row["identity"] and row["identity"] != identity for row in snapshots)
    samples = [row["gpu"] for row in snapshots if row["gpu"] is not None]
    return {
        "passed": error is None
        and all(value == "match" for value in checks.values())
        and not changed,
        "inference_passed": error is None,
        "error": error,
        "latency_seconds": round(elapsed, 3),
        "latency_scope": "model readiness plus synthetic inference",
        "identity": identity,
        "identity_checks": checks,
        "identity_changed": changed,
        "gpu": {
            "status": "sampled" if samples else "unavailable",
            "observed_peak_used_mib": max(
                (row["used_mib"] for row in samples), default=None
            ),
            "total_mib": max((row["total_mib"] for row in samples), default=None),
            "samples": len(samples),
            "scope": "visible device samples around inference; not guaranteed peak or per-process VRAM",
        },
    }


if __name__ == "__main__":
    import argparse
    import sys
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--status", action="store_true")
    mode.add_argument("--verify", action="store_true")
    parser.add_argument("--model")
    args = parser.parse_args()
    try:
        config = json.loads(Path("/opt/brokerage-gpu/config.json").read_text())
        env = dict(
            line.split("=", 1)
            for line in Path("/opt/brokerage-gpu/runtime.env").read_text().splitlines()
        )
        if config["workload"] == "general" and "GENERAL_MODEL_PROFILE" in env:
            from model_profiles import load_profile

            config["model"] = load_profile(env["GENERAL_MODEL_PROFILE"])["model"]
        if args.model is not None:
            if config["workload"] != "general":
                raise ValueError("explicit general model cannot be used for F2")
            config["model"] = args.model
        if args.verify:
            image = config.get("image")
            expected = {"image": image} if image else {}
            if config["workload"] == "general":
                from model_profiles import load_profile

                profile_name = env.get("GENERAL_MODEL_PROFILE")
                profile = load_profile(profile_name)
                expected.update(
                    model=profile["model"],
                    revision=profile["revision"],
                    profile=profile_name,
                )
                services = [
                    verify(
                        "http://127.0.0.1:8000/v1",
                        env["AI_GENERAL_API_KEY"],
                        config["model"],
                        expected_identity=expected,
                    )
                ]
            else:
                release = json.loads(
                    Path("/srv/brokerage-gpu/release.json").read_text()
                )
                base = release["base_model"]
                expected.update(
                    release_id=release["release_id"],
                    model=base["id"],
                    revision=base["revision"],
                )
                services = [
                    verify(
                        "http://127.0.0.1:8001/v1",
                        env["AI_VLLM_SLLM_API_KEY"],
                        "sllm",
                        expected_identity=expected,
                    )
                ]
                stt_expected = {"image": image} if image else {}
                stt_expected.update(
                    model=env["F2_STT_MODEL_ID"], revision=env["F2_STT_MODEL_REVISION"]
                )
                services.append(
                    verify(
                        "http://127.0.0.1:8002/v1",
                        env["AI_VLLM_STT_API_KEY"],
                        "stt",
                        stt=True,
                        expected_identity=stt_expected,
                    )
                )
            passed = all(row["passed"] for row in services)
            print(
                json.dumps(
                    {
                        "workload": config["workload"],
                        "passed": passed,
                        "services": services,
                    }
                )
            )
            sys.exit(0 if passed else 1)
        if args.status:
            result = {
                "model_ready": False,
                "disk_free_bytes": shutil.disk_usage("/srv/brokerage-gpu").free,
            }
            try:
                if config["workload"] == "general":
                    result["model_ready"] = read_status(
                        "http://127.0.0.1:8000/v1",
                        env["AI_GENERAL_API_KEY"],
                        config["model"],
                    )["model_ready"]
                else:
                    result["model_ready"] = all(
                        (
                            read_status(
                                "http://127.0.0.1:8001/v1",
                                env["AI_VLLM_SLLM_API_KEY"],
                                "sllm",
                            )["model_ready"],
                            read_status(
                                "http://127.0.0.1:8002/v1",
                                env["AI_VLLM_STT_API_KEY"],
                                "stt",
                            )["model_ready"],
                        )
                    )
            except (OSError, ValueError, KeyError):
                pass
            print(json.dumps(result))
            sys.exit(0)
        if config["workload"] == "general":
            probe(
                "http://127.0.0.1:8000/v1", env["AI_GENERAL_API_KEY"], config["model"]
            )
        else:
            probe("http://127.0.0.1:8001/v1", env["AI_VLLM_SLLM_API_KEY"], "sllm")
            probe(
                "http://127.0.0.1:8002/v1", env["AI_VLLM_STT_API_KEY"], "stt", stt=True
            )
        print("synthetic inference: OK")
    except (OSError, ValueError, KeyError, IndexError):
        print("synthetic inference failed", file=sys.stderr)
        sys.exit(1)
