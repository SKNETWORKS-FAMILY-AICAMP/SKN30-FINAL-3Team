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


if __name__ == "__main__":
    unittest.main()
