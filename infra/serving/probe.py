"""Synthetic inference probe. Never prints credentials or model response text."""

from __future__ import annotations

import io
import json
import shutil
import urllib.request
import wave


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


if __name__ == "__main__":
    import sys
    from pathlib import Path

    try:
        config = json.loads(Path("/opt/brokerage-gpu/config.json").read_text())
        env = dict(
            line.split("=", 1)
            for line in Path("/opt/brokerage-gpu/runtime.env").read_text().splitlines()
        )
        if sys.argv[1:] == ["--status"]:
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
