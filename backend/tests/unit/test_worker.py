import threading
from pathlib import Path

import pytest

from core.errors import ConfigurationError
from worker import run_disabled_worker, worker_enabled


def test_worker_enabled_rejects_invalid_value() -> None:
    with pytest.raises(ConfigurationError, match="WORKER_ENABLED"):
        worker_enabled({"WORKER_ENABLED": "sometimes"})


def test_disabled_worker_checks_readiness_without_claiming(tmp_path: Path) -> None:
    ready_file = tmp_path / "worker-ready"
    stop_event = threading.Event()
    stop_event.set()
    probes: list[str] = []

    run_disabled_worker(
        stop_event=stop_event,
        ready_file=ready_file,
        readiness_probe=lambda: probes.append("ready"),
    )

    assert probes == ["ready"]
    assert not ready_file.exists()
