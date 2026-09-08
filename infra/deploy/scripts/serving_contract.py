"""Small, credential-free contracts shared by delivery and serving operations."""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

DEFAULT_GENERAL_PROFILE = "qwen38-27b-bnb"
# The pinned vLLM 0.28 image requires CUDA 13-capable hosts.
GENERAL_CUDA_VERSIONS = ("13.0",)
GENERAL_MODEL = "unsloth/Qwen3.8-27B-unsloth-bnb-4bit"
GENERAL_REVISION = "8aa5f05d26b7205477066e1449e0af13f762a299"
GENERAL_ALIAS = "general-dev-gpu"
GENERAL_KEY = "AI_GENERAL_API_KEY"
WORKLOADS = ("f2", "general")
PORTS = {"f2": (8001, 8002), "general": (8000,)}
POD_NAME = {"f2": "skn30-f2-serving-dev", "general": "skn30-general-serving-dev"}


def aws_base_url(
    value: object, *, instance_id: object, private_ip: object, port: int
) -> str:
    if not isinstance(instance_id, str) or not re.fullmatch(
        r"i-(?:[0-9a-f]{8}|[0-9a-f]{17})", instance_id
    ):
        raise ValueError("invalid managed GPU instance ID")
    try:
        address = ipaddress.ip_address(str(private_ip))
    except ValueError:
        raise ValueError("invalid GPU private IPv4") from None
    if address not in ipaddress.ip_network("10.30.0.0/16"):
        raise ValueError("GPU address must belong to the dev VPC")
    expected = f"http://{address}:{port}/v1"
    if value != expected:
        raise ValueError(
            "GPU URL must match the managed instance address and service port"
        )
    return expected


def endpoint_urls(
    cloud: str, resource: str, workload: str, private_ip: str | None = None
) -> list[str]:
    if workload not in WORKLOADS:
        raise ValueError("unknown serving workload")
    if cloud == "runpod" and re.fullmatch(r"[a-z0-9]{5,64}", resource):
        return [
            f"https://{resource}-{port}.proxy.runpod.net/v1" for port in PORTS[workload]
        ]
    if cloud == "aws":
        return [
            aws_base_url(
                f"http://{private_ip}:{port}/v1",
                instance_id=resource,
                private_ip=private_ip,
                port=port,
            )
            for port in PORTS[workload]
        ]
    raise ValueError("invalid serving deployment")


def validate_general_endpoint(entry: dict) -> None:
    if entry.get("alias") != GENERAL_ALIAS or entry.get("provider") != "vllm":
        raise ValueError("general GPU requires its fixed alias and vLLM provider")
    if entry.get("api_key_env") != GENERAL_KEY:
        raise ValueError("general GPU requires its dedicated API key")
    url = urlsplit(str(entry.get("base_url", "")))
    if url.username or url.password or url.query or url.fragment or url.path != "/v1":
        raise ValueError("invalid general endpoint URL")
    if url.scheme == "https" and re.fullmatch(
        r"[a-z0-9]{5,64}-8000\.proxy\.runpod\.net", url.netloc
    ):
        return
    if url.scheme == "http" and url.port == 8000:
        try:
            if ipaddress.ip_address(str(url.hostname)) in ipaddress.ip_network(
                "10.30.0.0/16"
            ):
                return
        except ValueError:
            pass
    raise ValueError("general GPU must use a managed private endpoint or RunPod HTTPS")
