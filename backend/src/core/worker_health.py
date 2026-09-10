"""Internal Worker health contract shared with the container probe."""

import os
from pathlib import Path

READY_FILE = Path("/tmp/brokerage-worker-ready")


def is_ready() -> bool:
    try:
        pid = int(READY_FILE.read_text())
        if pid <= 0:
            return False
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False
