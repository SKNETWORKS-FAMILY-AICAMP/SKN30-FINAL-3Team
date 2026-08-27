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
        self.assertIn("APP_ENV", buildspec)
        self.assertNotIn("APP_PROFILE", buildspec)
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
        self.assertIn("APP_PARAMETER_PREFIX", buildspec)
        self.assertIn("BACKEND_RUNTIME_DATABASE_SECRET_ID", buildspec)
        self.assertIn("AI_PROVIDER_SECRET_ID", buildspec)

    def test_deployment_metadata_does_not_expand_release_manifest(self) -> None:
        manifest_writer = read("infra/delivery/scripts/write_release_manifest.py")

        for name in (
            "APP_PARAMETER_PREFIX",
            "BACKEND_RUNTIME_DATABASE_SECRET_ID",
            "AI_PROVIDER_SECRET_ID",
            "APP_PORT",
        ):
            self.assertNotIn(name, manifest_writer)

    def test_frontend_verify_and_build_commands_stay_separate(self) -> None:
        verify_script = read("infra/delivery/scripts/verify_frontend.sh")
        build_script = read("infra/delivery/scripts/build_frontend_release.sh")
        verify_buildspec = read("infra/delivery/buildspec-frontend-verify.yml")
        build_buildspec = read("infra/delivery/buildspec-frontend-build.yml")

        self.assertIn("npm run typecheck", verify_script)
        self.assertIn("npm run test:ledger", verify_script)
        self.assertIn("npm run test:env", verify_script)
        self.assertIn("npm run test:auth", verify_script)
        self.assertNotIn("npm run build", verify_script)
        self.assertNotIn("npm run test:release", verify_script)
        self.assertIn("npm run build", build_script)
        self.assertIn("npm run test:release", build_script)
        self.assertIn("VITE_API_BASE_URL must be injected", build_script)
        self.assertIn('"${VITE_LEDGER_SOURCE:-}" != "api"', build_script)
        self.assertNotIn("npm run typecheck", build_script)
        self.assertNotIn("npm run test:ledger", build_script)
        self.assertNotIn("\nartifacts:", verify_buildspec)
        self.assertIn("\nartifacts:", build_buildspec)

    def test_all_pipelines_use_dev_and_separate_verify_from_build(self) -> None:
        terraform = read("infra/environments/dev/delivery.tf")

        self.assertEqual(terraform.count('BranchName           = "dev"'), 3)
        self.assertNotIn('BranchName           = "main"', terraform)
        self.assertEqual(terraform.count('name = "Verify"'), 3)
        self.assertEqual(terraform.count('name = "Build"'), 3)
        self.assertIn("aws_codebuild_project.backend_verify.name", terraform)
        self.assertIn("aws_codebuild_project.frontend_verify.name", terraform)
        self.assertIn("automatic_dev_delivery", terraform)
        self.assertNotIn("automatic_main_delivery", terraform)

    def test_nondefault_application_port_reaches_runtime_and_security(self) -> None:
        locals_tf = read("infra/environments/dev/locals.tf")
        runtime = read("infra/environments/dev/runtime.tf")
        security = read("infra/environments/dev/security.tf")

        self.assertIn(
            "application_port       = tonumber(local.application_environment.backend.APP_PORT)",
            locals_tf,
        )
        self.assertIn("port        = local.application_port", runtime)
        self.assertEqual(security.count("= local.application_port"), 4)
        self.assertNotIn("= 8000", security)

    def test_readiness_path_is_injected_without_expanding_release_manifest(
        self,
    ) -> None:
        terraform = read("infra/environments/dev/delivery.tf")
        admission = read("infra/delivery/scripts/check_pipeline_conflicts.sh")
        frontend_deploy = read("infra/delivery/buildspec-frontend-deploy.yml")

        self.assertEqual(terraform.count('name  = "APP_READINESS_PATH"'), 2)
        self.assertIn('"${BACKEND_ORIGIN}${APP_READINESS_PATH}"', admission)
        self.assertNotIn("${BACKEND_ORIGIN}/health/ready", admission)
        self.assertIn(
            '"https://${CLOUDFRONT_DOMAIN}${APP_READINESS_PATH}"', frontend_deploy
        )
        self.assertNotIn("${CLOUDFRONT_DOMAIN}/health/ready", frontend_deploy)

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
        self.assertIn(
            "FROM public.ecr.aws/docker/library/postgres:", database_dockerfile
        )
        self.assertEqual(
            database_dockerfile.count(
                "FROM public.ecr.aws/docker/library/postgres:15.18-bookworm"
            ),
            2,
        )
        self.assertIn("COPY --from=builder", database_dockerfile)
        self.assertNotIn("pgvector/pgvector", local_verify)

    def test_local_delivery_requires_compose_raw_support(self) -> None:
        local_verify = read("infra/delivery/scripts/verify_local_delivery.sh")

        self.assertIn('minimum_compose_version="2.30.0"', local_verify)
        self.assertIn("docker compose version --short", local_verify)
        self.assertIn("compose_major == 2 && compose_minor < 30", local_verify)
        self.assertIn("format: raw 계약", local_verify)

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
        self.assertIn(
            "${RDS_CA_CONTAINER_FILE:?RDS_CA_CONTAINER_FILE is required}", compose
        )
        self.assertNotIn(
            "${CONFIG_DIR:?CONFIG_DIR is required}:/opt/brokerage/config", compose
        )
        self.assertIn("test -r '${RDS_CA_CONTAINER_FILE}'", after_install)
        self.assertIn('required_environment("RDS_CA_CONTAINER_FILE")', render_env)

    def test_runtime_configuration_is_dynamic_and_secret_values_are_write_only(
        self,
    ) -> None:
        configuration = read("infra/environments/dev/configuration.tf")
        variables = read("infra/environments/dev/variables.tf")
        delivery = read("infra/environments/dev/delivery.tf")
        checks = read("infra/environments/dev/checks.tf")

        self.assertIn("application_environment = {", configuration)
        self.assertIn(
            "for namespace, values in local.application_environment", configuration
        )
        for previous_address in (
            "backend_auth_session_absolute_minutes",
            "backend_auth_session_idle_minutes",
            "backend_auth_session_last_seen",
            "backend_db_pool_timeout",
        ):
            self.assertIn(
                f'from = aws_ssm_parameter.application["{previous_address}"]',
                configuration,
            )
        self.assertIn(
            "secret_string_wo         = jsonencode(var.ai_provider_api_keys)",
            configuration,
        )
        self.assertNotIn("secret_string         =", configuration)
        self.assertIn("ephemeral   = true", variables)
        self.assertIn('length(regexall("[[:space:]]", value)) == 0', variables)
        self.assertIn(
            'length(regexall("[[:space:]]", var.discord_webhook_url)) == 0',
            variables,
        )
        self.assertIn("secret_string_wo         = var.discord_webhook_url", delivery)
        self.assertIn("frontend_build_environment = {", delivery)
        self.assertIn('dynamic "environment_variable"', delivery)
        self.assertIn('check "application_environment_names"', checks)
        self.assertIn('can(regex("^[A-Z][A-Z0-9_]*$", name))', checks)
        for reserved_name in ("DB_URL", "DB_MIGRATION_URL", "AWS_"):
            self.assertIn(reserved_name, checks)
        for suffix in (
            "_API_KEY",
            "_PASSWORD",
            "_PRIVATE_KEY",
            "_SECRET",
            "_TOKEN",
        ):
            self.assertIn(suffix, checks)
        self.assertIn('check "application_environment_namespaces_are_disjoint"', checks)
        self.assertIn("setintersection(", checks)
        self.assertIn('check "frontend_build_environment"', checks)
        self.assertIn('can(regex("^VITE_[A-Z0-9_]+$", name))', checks)
        self.assertIn('trimspace(value) != ""', checks)

    def test_development_auth_drives_backend_and_frontend_together(self) -> None:
        variables = read("infra/environments/dev/variables.tf")
        configuration = read("infra/environments/dev/configuration.tf")
        delivery = read("infra/environments/dev/delivery.tf")

        self.assertIn('variable "development_auth"', variables)
        self.assertIn("default   = null", variables)
        self.assertIn("nullable  = true", variables)
        self.assertIn("sensitive = false", variables)
        self.assertIn(
            "condition = var.development_auth == null ? true : (", variables
        )
        self.assertIn(
            "var.development_auth.brokerage_id == "
            "floor(var.development_auth.brokerage_id)",
            variables,
        )
        self.assertIn(
            "length(trimspace(var.development_auth.login_id)) >= 1", variables
        )
        self.assertIn(
            "length(trimspace(var.development_auth.login_id)) <= 100", variables
        )
        self.assertIn(
            "development_auth_enabled = var.development_auth != null",
            configuration,
        )
        self.assertIn(
            "development_auth == null ? tomap({}) : tomap({", configuration
        )
        self.assertIn("AUTH_DEVELOPMENT_BROKERAGE_ID", configuration)
        self.assertIn("AUTH_DEVELOPMENT_LOGIN_ID", configuration)
        self.assertIn(
            "AUTH_DEVELOPMENT_ENABLED              = "
            "tostring(local.development_auth_enabled)",
            configuration,
        )
        self.assertIn(
            "VITE_AUTH_DEVELOPMENT_ENABLED = "
            "tostring(local.development_auth_enabled)",
            delivery,
        )

    def test_deployed_backend_uses_dev_profile_and_short_session_timeouts(
        self,
    ) -> None:
        configuration = read("infra/environments/dev/configuration.tf")

        for setting in (
            'APP_ENV                               = "dev"',
            'DB_TARGET                             = "development"',
            'AUTH_SESSION_IDLE_TIMEOUT_MINUTES     = "30"',
            'AUTH_SESSION_ABSOLUTE_TIMEOUT_MINUTES = "720"',
        ):
            self.assertIn(setting, configuration)
        self.assertNotIn('APP_ENV                               = "prod"', configuration)
        self.assertNotIn('DB_TARGET                             = "production"', configuration)

    def test_account_link_setup_does_not_require_application_secrets(self) -> None:
        verification = read("infra/scripts/verify-account-link.sh")
        justfile = read("infra/justfile")

        self.assertIn("state pull", verification)
        self.assertNotIn("secrets.auto.tfvars", verification)
        self.assertNotIn(
            'terraform -chdir="$infra_dir/environments/dev" plan', verification
        )
        self.assertIn("dev-plan: require-dev-secrets", justfile)
        self.assertNotIn("setup expires_at: require-dev-secrets", justfile)
        self.assertNotIn("setup-existing expires_at: require-dev-secrets", justfile)
        self.assertNotIn("verify-account: require-dev-secrets", justfile)
        self.assertIn(
            'test -f "$secret_file" && test ! -L "$secret_file" && test -s "$secret_file"',
            justfile,
        )
        self.assertIn("stat -c '%a'", justfile)
        self.assertIn('case "$secret_mode" in *00)', justfile)

    def test_dev_destroy_requires_a_reviewed_saved_plan(self) -> None:
        justfile = read("infra/justfile")
        gitignore = read(".gitignore")

        self.assertIn("dev-destroy-plan: require-dev-secrets", justfile)
        self.assertIn(
            "terraform -chdir=environments/dev plan -destroy -input=false "
            "-var-file=dev.tfvars -out=dev-destroy.tfplan",
            justfile,
        )
        self.assertIn(
            "dev-destroy-show:\n"
            "    terraform -chdir=environments/dev show dev-destroy.tfplan",
            justfile,
        )
        self.assertIn("dev-destroy: require-dev-secrets", justfile)
        self.assertIn(
            "terraform -chdir=environments/dev apply dev-destroy.tfplan",
            justfile,
        )
        self.assertNotIn("terraform -chdir=environments/dev destroy", justfile)
        self.assertIn("*.tfplan", gitignore)

    def test_dev_secret_gate_rejects_missing_empty_and_shared_files(self) -> None:
        justfile = read("infra/justfile")
        recipe = justfile.split("require-dev-secrets:\n", maxsplit=1)[1]
        gate_command = recipe.splitlines()[0].strip().removeprefix("@")

        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            secret_dir = root / "environments/dev"
            secret_dir.mkdir(parents=True)
            secret_file = secret_dir / "secrets.auto.tfvars"

            missing = subprocess.run(
                ["sh", "-c", gate_command],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(missing.returncode, 0)

            secret_file.touch(mode=0o600)
            empty = subprocess.run(
                ["sh", "-c", gate_command],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(empty.returncode, 0)

            secret_file.write_text('discord_webhook_url = "placeholder"\n')
            secret_file.chmod(0o644)
            shared = subprocess.run(
                ["sh", "-c", gate_command],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(shared.returncode, 0)

            secret_file.chmod(0o600)
            owner_only = subprocess.run(
                ["sh", "-c", gate_command],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(owner_only.returncode, 0)

            secret_file.rename(secret_dir / "actual-secrets.tfvars")
            secret_file.symlink_to(secret_dir / "actual-secrets.tfvars")
            symlink = subprocess.run(
                ["sh", "-c", gate_command],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(symlink.returncode, 0)

    def test_compose_uses_process_specific_environment_files(self) -> None:
        compose = read("infra/deploy/compose.dev.yml")
        common = read("infra/deploy/scripts/common.sh")

        self.assertIn("${API_ENV_FILE:?API_ENV_FILE is required}", compose)
        self.assertIn("${WORKER_ENV_FILE:?WORKER_ENV_FILE is required}", compose)
        self.assertIn("${MIGRATION_ENV_FILE:?MIGRATION_ENV_FILE is required}", compose)
        self.assertEqual(compose.count("format: raw"), 3)
        self.assertNotIn("RUNTIME_ENV_FILE", compose)
        self.assertIn('API_ENV_FILE="${CONFIG_DIR}/api.env"', common)
        self.assertIn('WORKER_ENV_FILE="${CONFIG_DIR}/worker.env"', common)
        self.assertIn(
            "docker/compose/releases/download/v2.35.1/",
            read("infra/environments/dev/runtime.tf"),
        )

    def test_before_install_removes_only_legacy_combined_environment_file(self) -> None:
        before_install = read("infra/deploy/scripts/before_install.sh")

        self.assertIn("rm -f -- /opt/brokerage/config/runtime.env", before_install)
        self.assertNotIn("rm -rf -- /opt/brokerage/config", before_install)

    def test_migration_profile_renders_rds_ca_file_mount(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config"
            config.mkdir(mode=0o700)
            ca_file = config / "global-bundle.pem"
            api_env = Path(directory) / "api.env"
            worker_env = Path(directory) / "worker.env"
            migration_env = Path(directory) / "migration.env"
            ca_file.touch(mode=0o644)
            api_env.write_text("APP_ENV=prod\nRAW_SENTINEL=api$literal#hash\n")
            worker_env.write_text("APP_ENV=prod\nRAW_SENTINEL=worker$literal#hash\n")
            migration_env.write_text(
                "DB_MIGRATION_URL=postgresql://migration:$literal#hash@database/dev\n"
            )
            api_env.chmod(0o600)
            worker_env.chmod(0o600)
            migration_env.chmod(0o600)

            environment = dict(os.environ)
            environment.update(
                {
                    "BACKEND_IMAGE": "repository@sha256:" + ("a" * 64),
                    "API_ENV_FILE": str(api_env),
                    "WORKER_ENV_FILE": str(worker_env),
                    "MIGRATION_ENV_FILE": str(migration_env),
                    "RDS_CA_FILE": str(ca_file),
                    "RDS_CA_CONTAINER_FILE": "/etc/ssl/certs/aws-rds-global-bundle.pem",
                    "AWS_REGION": "ap-northeast-2",
                    "APP_PORT": "8000",
                    "APP_READINESS_PATH": "/health/ready",
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

        # Compose config escapes a literal runtime '$' as '$$'; losing raw mode
        # would interpolate '$literal' before this canonical representation.
        self.assertEqual(
            compose["services"]["api"]["environment"]["RAW_SENTINEL"],
            "api$$literal#hash",
        )
        self.assertEqual(
            compose["services"]["worker"]["environment"]["RAW_SENTINEL"],
            "worker$$literal#hash",
        )
        self.assertEqual(
            compose["services"]["migrate"]["environment"]["DB_MIGRATION_URL"],
            "postgresql://migration:$$literal#hash@database/dev",
        )

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
