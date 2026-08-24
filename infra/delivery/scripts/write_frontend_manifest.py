#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--pipeline", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--execution", required=True)
    args = parser.parse_args()

    assets = []
    for path in sorted(item for item in args.site.rglob("*") if item.is_file()):
        content = path.read_bytes()
        assets.append(
            {
                "path": path.relative_to(args.site).as_posix(),
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    args.output.write_text(
        json.dumps(
            {
                "pipeline": args.pipeline,
                "revision": args.revision,
                "execution_id": args.execution,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "entry_document": "index.html",
                "assets": assets,
                "bundle_bytes": sum(item["bytes"] for item in assets),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
