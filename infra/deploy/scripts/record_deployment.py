#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    record = json.loads(args.manifest.read_text(encoding="utf-8"))
    record["migration"] = "applied"
    record["deployed_at"] = datetime.now(timezone.utc).isoformat()
    args.output.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.output.chmod(0o644)


if __name__ == "__main__":
    main()
