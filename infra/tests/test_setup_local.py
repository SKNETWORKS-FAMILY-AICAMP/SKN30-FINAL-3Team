import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SETUP_SCRIPT = REPOSITORY_ROOT / "infra/scripts/setup-local.sh"


class SetupLocalTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(dir="/tmp")
        self.root = Path(self.temporary_directory.name)
        self.infra = self.root / "infra"
        self.scripts = self.infra / "scripts"
        self.dev = self.infra / "environments/dev"
        self.bootstrap = self.infra / "bootstrap"
        self.bin = self.root / "bin"
        for directory in (self.scripts, self.dev, self.bootstrap, self.bin):
            directory.mkdir(parents=True, exist_ok=True)

        self.setup_script = self.scripts / "setup-local.sh"
        shutil.copy2(SETUP_SCRIPT, self.setup_script)
        self._write_executable(self.scripts / "preflight.sh", "#!/bin/sh\nexit 0\n")
        self._write_executable(
            self.scripts / "verify-account-link.sh", "#!/bin/sh\nexit 0\n"
        )
        self._write_executable(
            self.bin / "terraform",
            "#!/bin/sh\nexit 0\n",
        )
        self._write_executable(
            self.bin / "aws",
            """#!/usr/bin/env bash
set -euo pipefail
if [[ "$1 $2" == "configure get" ]]; then
  exit 0
fi
if [[ "$1 $2" == "configure set" ]]; then
  exit 0
fi
if [[ "$1" == "login" ]]; then
  exit 0
fi
if [[ "$1 $2" == "sts get-caller-identity" ]]; then
  if [[ " $* " == *" --query Account "* ]]; then
    printf '%s\n' "${STUB_AWS_ACCOUNT}"
  else
    printf 'arn:aws:iam::%s:user/developer\n' "${STUB_AWS_ACCOUNT}"
  fi
  exit 0
fi
printf 'unsupported aws invocation: %s\n' "$*" >&2
exit 2
""",
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    @staticmethod
    def _write_executable(path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)

    def _run(
        self,
        *,
        account_id: str = "123456789012",
        expires_at: str = "2026-09-23",
        force: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        command = [
            str(self.setup_script),
            "--account-id",
            account_id,
            "--expires-at",
            expires_at,
            "--skip-login",
        ]
        if force:
            command.append("--force")
        environment = dict(os.environ)
        environment["PATH"] = f"{self.bin}:{environment['PATH']}"
        environment["STUB_AWS_ACCOUNT"] = account_id
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )

    def test_existing_development_auth_is_preserved_even_with_force(self) -> None:
        tfvars = self.dev / "dev.tfvars"
        original = """target_account_id = "123456789012"
expires_at = "2026-09-23"
pipeline_operator_user_names = ["developer"]

development_auth = {
  brokerage_id = 7
  login_id      = "developer"
}
"""
        tfvars.write_text(original, encoding="utf-8")

        result = self._run(force=True)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(tfvars.read_text(encoding="utf-8"), original)
        self.assertIn(f"유지: {tfvars}", result.stdout)

    def test_existing_account_id_mismatch_fails_without_overwriting(self) -> None:
        tfvars = self.dev / "dev.tfvars"
        original = """target_account_id = "111111111111"
expires_at = "2026-09-23"
development_auth = {
  brokerage_id = 7
  login_id      = "developer"
}
"""
        tfvars.write_text(original, encoding="utf-8")

        result = self._run(force=True)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("target_account_id가 요청값과 다릅니다", result.stderr)
        self.assertEqual(tfvars.read_text(encoding="utf-8"), original)
        self.assertFalse((self.bootstrap / "backend.hcl").exists())

    def test_existing_expiration_mismatch_fails_without_overwriting(self) -> None:
        tfvars = self.dev / "dev.tfvars"
        original = """target_account_id = "123456789012"
expires_at = "2026-09-22"
development_auth = null
"""
        tfvars.write_text(original, encoding="utf-8")

        result = self._run(force=True)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("expires_at이 요청값과 다릅니다", result.stderr)
        self.assertEqual(tfvars.read_text(encoding="utf-8"), original)
        self.assertFalse((self.bootstrap / "backend.hcl").exists())

    def test_existing_dev_tfvars_symlink_is_rejected(self) -> None:
        actual = self.dev / "actual.tfvars"
        original = """target_account_id = "123456789012"
expires_at = "2026-09-23"
development_auth = null
"""
        actual.write_text(original, encoding="utf-8")
        tfvars = self.dev / "dev.tfvars"
        tfvars.symlink_to(actual)

        result = self._run(force=True)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("symbolic link가 아닌 일반 파일", result.stderr)
        self.assertTrue(tfvars.is_symlink())
        self.assertEqual(actual.read_text(encoding="utf-8"), original)
        self.assertFalse((self.bootstrap / "backend.hcl").exists())

    def test_missing_dev_tfvars_is_created_fail_closed(self) -> None:
        tfvars = self.dev / "dev.tfvars"

        result = self._run()

        self.assertEqual(result.returncode, 0, result.stderr)
        content = tfvars.read_text(encoding="utf-8")
        self.assertIn('target_account_id = "123456789012"', content)
        self.assertIn('expires_at        = "2026-09-23"', content)
        self.assertIn(
            'expires_at        = "2026-09-23"\n\ndevelopment_auth = null',
            content,
        )


if __name__ == "__main__":
    unittest.main()
