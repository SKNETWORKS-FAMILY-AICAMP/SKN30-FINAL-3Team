#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--pipeline", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--execution", required=True)
    parser.add_argument("--image-digest", required=True)
    parser.add_argument("--migration", required=True)
    args = parser.parse_args()
    args.output.write_text(
        json.dumps(
            {
                "pipeline": args.pipeline,
                "revision": args.revision,
                "execution_id": args.execution,
                "image_digest": args.image_digest,
                "migration": args.migration,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
