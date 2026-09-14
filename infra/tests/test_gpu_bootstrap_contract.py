import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class GpuBootstrapContractTests(unittest.TestCase):
    def test_large_bootstrap_files_use_a_hashed_s3_artifact(self) -> None:
        terraform = (REPOSITORY_ROOT / "infra/environments/dev/serving.tf").read_text(
            encoding="utf-8"
        )
        user_data = (REPOSITORY_ROOT / "infra/serving/user-data.sh.tftpl").read_text(
            encoding="utf-8"
        )

        self.assertIn('data "archive_file" "gpu_bootstrap"', terraform)
        self.assertIn('resource "aws_s3_object" "gpu_bootstrap"', terraform)
        self.assertIn("data.archive_file.gpu_bootstrap.output_sha256", terraform)
        self.assertIn('check "gpu_user_data_encoded_size"', terraform)
        self.assertIn("length(instance.user_data_base64) <= 25600", terraform)
        self.assertIn("aws s3api get-object", user_data)
        self.assertIn("sha256sum -c -", user_data)
        self.assertNotIn("${host_script}", user_data)
        self.assertNotIn("${probe_script}", user_data)

    def test_stopped_gpu_keeps_its_model_cache(self) -> None:
        terraform = (REPOSITORY_ROOT / "infra/environments/dev/serving.tf").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "ignore_changes = [associate_public_ip_address, user_data_base64]",
            terraform,
        )
        self.assertIn("delete_on_termination = true", terraform)

    def test_gpu_host_failure_reports_only_a_safe_stage(self) -> None:
        host = (REPOSITORY_ROOT / "infra/serving/gpu_host.py").read_text(
            encoding="utf-8"
        )
        lifecycle = (REPOSITORY_ROOT / "infra/scripts/manage_serving.py").read_text(
            encoding="utf-8"
        )

        for stage in (
            "selection",
            "runtime-secrets",
            "image-pull",
            "f2-bootstrap",
            "model-download",
            "compose-start",
        ):
            self.assertIn(f'record_stage("{stage}")', host)
        self.assertIn('{"stage": CURRENT_STAGE, "status": "failed"}', host)
        self.assertNotIn("str(error)", host)
        self.assertIn("cat /opt/brokerage-gpu/status.json >&2", lifecycle)

    def test_gpu_host_creates_the_status_disk_path(self) -> None:
        host = (REPOSITORY_ROOT / "infra/serving/gpu_host.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('(DATA / "cache" / "huggingface").mkdir(exist_ok=True)', host)


if __name__ == "__main__":
    unittest.main()
