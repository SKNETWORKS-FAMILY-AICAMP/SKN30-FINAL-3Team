import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
COMMON_SCRIPT = REPOSITORY_ROOT / "infra/deploy/scripts/common.sh"
IMAGE_DIGEST = "sha256:" + ("a" * 64)
BACKEND_IMAGE = (
    "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/backend@" + IMAGE_DIGEST
)


class DeliveryCommonScriptTests(unittest.TestCase):
    def release_metadata(self, image: str = BACKEND_IMAGE) -> str:
        return "\n".join(
            (
                f"BACKEND_IMAGE={image}",
                "AI_PROVIDER_SECRET_ID=ai-secret",
                "API_LOG_GROUP=/application/api",
                "APP_PARAMETER_PREFIX=/project-dev",
                "APP_PORT=8000",
                "APP_READINESS_PATH=/health/ready",
                "AWS_REGION=ap-northeast-2",
                "BACKEND_RUNTIME_DATABASE_SECRET_ID=database-secret",
                "WORKER_LOG_GROUP=/application/worker",
                "",
            )
        )

    def run_common(
        self, image_metadata: str | None, *, require_image: bool = True
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            app_root = Path(directory) / "brokerage"
            revision = app_root / "revision"
            revision.mkdir(parents=True)
            if image_metadata is not None:
                (revision / "backend-image.env").write_text(
                    image_metadata, encoding="utf-8"
                )

            script = COMMON_SCRIPT.read_text(encoding="utf-8").replace(
                "readonly APP_ROOT=/opt/brokerage",
                f"readonly APP_ROOT={app_root}",
                1,
            )
            environment = dict(os.environ)
            environment.pop("BACKEND_IMAGE", None)
            environment["INSTANCE_ID"] = "i-local"
            validation = "require_backend_image; " if require_image else ""
            command = (
                "source /dev/stdin; "
                + validation
                + 'bash -c \'printf "%s" "${BACKEND_IMAGE}"\''
            )
            return subprocess.run(
                ["bash", "-c", command],
                input=script,
                capture_output=True,
                text=True,
                env=environment,
                check=False,
            )

    def test_backend_image_is_exported_to_child_processes(self) -> None:
        result = self.run_common(self.release_metadata())

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, BACKEND_IMAGE)

    def test_missing_backend_image_metadata_fails_early(self) -> None:
        result = self.run_common(None)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing Backend image release metadata", result.stderr)

    def test_missing_metadata_does_not_block_stop_loader(self) -> None:
        result = self.run_common(None, require_image=False)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_mutable_backend_image_reference_is_rejected(self) -> None:
        result = self.run_common(self.release_metadata("repository:latest"))

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("BACKEND_IMAGE must be pinned to an ECR digest", result.stderr)

    def test_missing_deployment_metadata_is_rejected(self) -> None:
        result = self.run_common(f"BACKEND_IMAGE={BACKEND_IMAGE}\n")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing Backend deployment metadata", result.stderr)


if __name__ == "__main__":
    unittest.main()
