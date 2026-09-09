"""Best-effort device memory samples; unavailable is distinct from zero usage."""

import re
import subprocess

IDENTITY_PATTERNS = {
    "image": r"ghcr\.io/sknetworks-family-aicamp/skn30-final-3team/(?:f2|general)-serving@sha256:[0-9a-f]{64}",
    "model": r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*",
    "revision": r"[0-9a-f]{40}",
    "profile": r"qwen(?:3-14b-awq|3-32b-awq|38-27b-bnb|38-27b-fp8)",
    "release_id": r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}",
    "artifact_sha256": r"[0-9a-f]{64}",
}


def safe_identity(value: object) -> dict:
    if not isinstance(value, dict):
        return {}
    return {
        key: value[key]
        for key, pattern in IDENTITY_PATTERNS.items()
        if isinstance(value.get(key), str) and re.fullmatch(pattern, value[key])
    }


def sample_gpu() -> dict:
    """Measure visible devices once. Device totals include other processes."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=2,
            check=True,
        )
        rows = [
            tuple(int(part.strip()) for part in row.split(","))
            for row in result.stdout.splitlines()
        ]
        if not rows or any(
            len(row) != 2 or not 0 <= row[0] <= row[1] or row[1] == 0 for row in rows
        ):
            raise ValueError("invalid device sample")
        return {
            "status": "sampled",
            "used_mib": sum(row[0] for row in rows),
            "total_mib": sum(row[1] for row in rows),
            "device_count": len(rows),
        }
    except (OSError, ValueError, subprocess.SubprocessError):
        return {
            "status": "unavailable",
            "used_mib": None,
            "total_mib": None,
            "device_count": None,
        }
