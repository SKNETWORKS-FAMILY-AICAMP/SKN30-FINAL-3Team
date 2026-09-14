"""Exercise the deployment shell without Docker, AWS or application processes."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infra/deploy/scripts/refresh_ai_endpoints.sh"


class RefreshEndpointTests(unittest.TestCase):
    def run_refresh(self, *, full=False, render_fails=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scripts = root / "scripts"
            scripts.mkdir()
            calls = root / "calls"
            (root / "release-manifest.json").write_text("release")
            (root / "backend-image.env").write_text("image")
            (root / "api.env").write_text("api-original")
            (root / "worker.env").write_text("worker-original")
            (root / "migration.env").write_text("migration-original")
            common = root / "common.sh"
            common.write_text("""set -euo pipefail
REVISION_DIR="$TEST_ROOT"
BACKEND_IMAGE_FILE="$TEST_ROOT/backend-image.env"
API_ENV_FILE="$TEST_ROOT/api.env"
WORKER_ENV_FILE="$TEST_ROOT/worker.env"
MIGRATION_ENV_FILE="$TEST_ROOT/migration.env"
BACKEND_IMAGE=image
require_backend_image() { :; }
docker() {
  if [[ "$*" == *".Config.Image"* ]]; then echo image; else echo image-id; fi
}
compose() { echo "$*" >> "$TEST_ROOT/calls"; }
""")
            (scripts / "render_env.py").write_text("""import json, os, sys
from pathlib import Path
root = Path(os.environ["TEST_ROOT"])
(root / "render-args.json").write_text(json.dumps(sys.argv[1:]))
if os.environ.get("RENDER_FAIL") == "1":
    raise SystemExit(2)
(root / "api.env").write_text("api-refreshed")
if "--f2-only" not in sys.argv:
    (root / "worker.env").write_text("worker-refreshed")
    (root / "migration.env").write_text("migration-refreshed")
""")
            validate = scripts / "validate_service.sh"
            validate.write_text("#!/usr/bin/env bash\nexit 0\n")
            validate.chmod(0o755)
            script = root / "refresh.sh"
            script.write_text(
                SCRIPT.read_text().replace(
                    "source /opt/brokerage/revision/scripts/common.sh",
                    f'source "{common}"',
                )
            )
            result = subprocess.run(
                ["bash", str(script), *(["--all"] if full else [])],
                env={
                    **os.environ,
                    "TEST_ROOT": str(root),
                    "RENDER_FAIL": str(int(render_fails)),
                },
                capture_output=True,
                text=True,
                check=False,
            )
            return (
                result,
                calls.read_text() if calls.exists() else "",
                (root / "worker.env").read_text(),
                (root / "migration.env").read_text(),
                json.loads((root / "render-args.json").read_text()),
            )

    def test_f2_refresh_only_recreates_api_and_preserves_worker_and_migration(self):
        result, calls, worker, migration, arguments = self.run_refresh()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--f2-only", arguments)
        self.assertIn(
            "up --detach --no-deps --force-recreate --pull never api\n", calls
        )
        self.assertNotIn("worker", calls)
        self.assertEqual(worker, "worker-original")
        self.assertEqual(migration, "migration-original")

    def test_general_secret_refresh_explicitly_recreates_both_consumers(self):
        result, calls, worker, _, arguments = self.run_refresh(full=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("--f2-only", arguments)
        self.assertIn("--pull never api worker\n", calls)
        self.assertEqual(worker, "worker-refreshed")

    def test_invalid_configuration_cannot_restart_any_container(self):
        result, calls, worker, migration, _ = self.run_refresh(render_fails=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, "")
        self.assertEqual(worker, "worker-original")
        self.assertEqual(migration, "migration-original")


if __name__ == "__main__":
    unittest.main()
