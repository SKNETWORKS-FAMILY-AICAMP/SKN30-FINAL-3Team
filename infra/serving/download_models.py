"""Download exact model revisions once, inside a disposable image container."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path


def download(items: list[dict]) -> None:
    from huggingface_hub import snapshot_download

    for item in items:
        path = Path(item["path"])
        marker = path / ".serving-revision"
        identity = item["model"] + "@" + item["revision"]
        if path.exists() and (not marker.exists() or marker.read_text() != identity):
            shutil.rmtree(path)
        # A failed integrity check must not leave a previously successful marker.
        marker.unlink(missing_ok=True)
        snapshot_download(
            repo_id=item["model"], revision=item["revision"], local_dir=item["path"]
        )
        for weight in item.get("weights", []):
            name = weight["name"]
            if Path(name).name != name or name in {"", ".", ".."}:
                raise ValueError("invalid model weight filename")
            weight_path = path / name
            if weight_path.stat().st_size != weight["size"]:
                raise ValueError("downloaded model weight size mismatch")
            with weight_path.open("rb") as source:
                digest = hashlib.file_digest(source, "sha256").hexdigest()
            if digest != weight["sha256"]:
                raise ValueError("downloaded model weight digest mismatch")
        marker.write_text(identity)


if __name__ == "__main__":
    download(json.loads(Path(sys.argv[1]).read_text()))
