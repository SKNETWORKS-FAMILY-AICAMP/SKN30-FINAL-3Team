import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DELIVERY_ROOT = REPOSITORY_ROOT / "infra/delivery"


def read(relative_path: str) -> str:
    return (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")


class DeliveryPipelineContractTests(unittest.TestCase):
    def test_backend_verify_owns_database_checks_without_artifacts(self) -> None:
        buildspec = read("infra/delivery/buildspec-backend-verify.yml")

        self.assertIn("TEST_DB_URL", buildspec)
        self.assertIn("verify_backend_ai.sh", buildspec)
        self.assertIn("CI_PGVECTOR_REPOSITORY_URI", buildspec)
        self.assertNotIn("\nartifacts:", buildspec)
        self.assertNotIn("_backend_release", buildspec)

    def test_backend_build_owns_release_without_test_database(self) -> None:
        buildspec = read("infra/delivery/buildspec-backend-build.yml")

        self.assertIn("_backend_release", buildspec)
        self.assertIn("backend-image.env", buildspec)
        self.assertIn("\nartifacts:", buildspec)
        self.assertNotIn("TEST_DB_URL", buildspec)
        self.assertNotIn("verify_backend_ai.sh", buildspec)
        self.assertNotIn("docker run", buildspec)

    def test_frontend_verify_and_build_commands_stay_separate(self) -> None:
        verify_script = read("infra/delivery/scripts/verify_frontend.sh")
        build_script = read("infra/delivery/scripts/build_frontend_release.sh")
        verify_buildspec = read("infra/delivery/buildspec-frontend-verify.yml")
        build_buildspec = read("infra/delivery/buildspec-frontend-build.yml")

        self.assertIn("npm run typecheck", verify_script)
        self.assertIn("npm run test:ledger", verify_script)
        self.assertNotIn("npm run build", verify_script)
        self.assertNotIn("npm run test:release", verify_script)
        self.assertIn("npm run build", build_script)
        self.assertIn("npm run test:release", build_script)
        self.assertNotIn("npm run typecheck", build_script)
        self.assertNotIn("npm run test:ledger", build_script)
        self.assertNotIn("\nartifacts:", verify_buildspec)
        self.assertIn("\nartifacts:", build_buildspec)

    def test_all_pipelines_use_main_and_separate_verify_from_build(self) -> None:
        terraform = read("infra/environments/dev/delivery.tf")

        self.assertEqual(terraform.count('BranchName           = "main"'), 3)
        self.assertNotIn('BranchName           = "dev"', terraform)
        self.assertEqual(terraform.count('name = "Verify"'), 3)
        self.assertEqual(terraform.count('name = "Build"'), 3)
        self.assertIn("aws_codebuild_project.backend_verify.name", terraform)
        self.assertIn("aws_codebuild_project.frontend_verify.name", terraform)

    def test_app_instance_uses_valid_rds_db_user_arn(self) -> None:
        terraform = read("infra/environments/dev/runtime.tf")

        self.assertIn(
            ":dbuser:${aws_db_instance.postgres.resource_id}/app_migrator",
            terraform,
        )
        self.assertNotIn(
            ":dbuser/${aws_db_instance.postgres.resource_id}/app_migrator",
            terraform,
        )

    def test_delivery_images_do_not_depend_on_docker_hub(self) -> None:
        backend_dockerfile = read("backend/Dockerfile")
        database_dockerfile = read("infra/delivery/docker/pgvector-ci.Dockerfile")
        local_verify = read("infra/delivery/scripts/verify_local_delivery.sh")

        self.assertIn("FROM public.ecr.aws/docker/library/python:", backend_dockerfile)
        self.assertIn("FROM public.ecr.aws/docker/library/postgres:", database_dockerfile)
        self.assertEqual(
            database_dockerfile.count(
                "FROM public.ecr.aws/docker/library/postgres:15.18-bookworm"
            ),
            2,
        )
        self.assertIn("COPY --from=builder", database_dockerfile)
        self.assertNotIn("pgvector/pgvector", local_verify)

    def test_legacy_combined_buildspecs_are_removed(self) -> None:
        self.assertFalse((DELIVERY_ROOT / "buildspec-backend.yml").exists())
        self.assertFalse((DELIVERY_ROOT / "buildspec-frontend.yml").exists())

    def test_rds_ca_is_mounted_without_exposing_root_only_config(self) -> None:
        common = read("infra/deploy/scripts/common.sh")
        compose = read("infra/deploy/compose.dev.yml")
        after_install = read("infra/deploy/scripts/after_install.sh")
        render_env = read("infra/deploy/scripts/render_env.py")

        self.assertIn('RDS_CA_FILE="${CONFIG_DIR}/global-bundle.pem"', common)
        self.assertIn(
            'RDS_CA_CONTAINER_FILE="/etc/ssl/certs/aws-rds-global-bundle.pem"',
            common,
        )
        self.assertIn("${RDS_CA_FILE:?RDS_CA_FILE is required}", compose)
        self.assertIn("${RDS_CA_CONTAINER_FILE:?RDS_CA_CONTAINER_FILE is required}", compose)
        self.assertNotIn("${CONFIG_DIR:?CONFIG_DIR is required}:/opt/brokerage/config", compose)
        self.assertIn("test -r '${RDS_CA_CONTAINER_FILE}'", after_install)
        self.assertIn('os.environ.get("RDS_CA_CONTAINER_FILE", "")', render_env)

    def test_migration_profile_renders_rds_ca_file_mount(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config"
            config.mkdir(mode=0o700)
            ca_file = config / "global-bundle.pem"
            runtime_env = Path(directory) / "runtime.env"
            migration_env = Path(directory) / "migration.env"
            ca_file.touch(mode=0o644)
            runtime_env.touch(mode=0o600)
            migration_env.touch(mode=0o600)

            environment = dict(os.environ)
            environment.update(
                {
                    "BACKEND_IMAGE": "repository@sha256:" + ("a" * 64),
                    "RUNTIME_ENV_FILE": str(runtime_env),
                    "MIGRATION_ENV_FILE": str(migration_env),
                    "RDS_CA_FILE": str(ca_file),
                    "RDS_CA_CONTAINER_FILE": "/etc/ssl/certs/aws-rds-global-bundle.pem",
                    "AWS_REGION": "ap-northeast-2",
                    "API_LOG_GROUP": "local-api",
                    "WORKER_LOG_GROUP": "local-worker",
                    "INSTANCE_ID": "local",
                }
            )
            result = subprocess.run(
                [
                    "docker",
                    "compose",
                    "--file",
                    str(DELIVERY_ROOT.parent / "deploy/compose.dev.yml"),
                    "--profile",
                    "migration",
                    "config",
                    "--format",
                    "json",
                ],
                check=True,
                capture_output=True,
                text=True,
                env=environment,
            )
            compose = json.loads(result.stdout)

        for service_name in ("api", "worker", "migrate"):
            self.assertEqual(
                compose["services"][service_name]["volumes"],
                [
                    {
                        "type": "bind",
                        "source": str(ca_file),
                        "target": "/etc/ssl/certs/aws-rds-global-bundle.pem",
                        "read_only": True,
                        "bind": {},
                    }
                ],
            )


if __name__ == "__main__":
    unittest.main()
