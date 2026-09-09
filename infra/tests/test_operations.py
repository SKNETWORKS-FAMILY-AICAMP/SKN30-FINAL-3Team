"""Operator safety: no secret output, no startup in diagnostics, no stale plans."""

import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import env_doctor
import plan_guard
import release_tools

import operations


class EnvironmentSafety(unittest.TestCase):
    def test_nonlocal_backend_diagnostics_ignore_dotenv_values(self):
        with patch.dict("os.environ", {"APP_ENV": "dev"}, clear=True):
            resolved = env_doctor.effective_values(
                "backend",
                {"WORKER_ENABLED": "true"},
                {"F3_ALLOW_SYNTHETIC_PROTOTYPE": "true"},
            )
        self.assertEqual(resolved, {"APP_ENV": "dev"})

    def test_local_auth_layers_report_mismatch_without_private_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "backend").mkdir()
            (root / "frontend").mkdir()
            (root / "backend/.env.local").write_text("AUTH_DEVELOPMENT_ENABLED=false\n")
            (root / "frontend/.env.local").write_text(
                "VITE_AUTH_DEVELOPMENT_ENABLED=true\n"
            )
            with patch.dict("os.environ", {}, clear=True):
                checks = env_doctor.inspect(root)
        self.assertTrue(
            any(c["target"] == "개발 인증" and c["status"] == "warn" for c in checks)
        )

    def test_consumer_names_are_documented_without_a_second_schema(self):
        root = Path(__file__).resolve().parents[2]
        for module in ("backend", "ai", "frontend"):
            names = env_doctor.environment_names(root, module)
            documented = set()
            for suffix in ("local", "example"):
                documented.update(
                    env_doctor.documented_names(
                        (root / module / (".env." + suffix)).read_text()
                    )
                )
            self.assertTrue(names)
            self.assertEqual(names - documented, set(), module)
        self.assertIn("CHATBOT_ENABLED", env_doctor.environment_names(root, "backend"))
        self.assertIn(
            "F3_ALLOW_SYNTHETIC_PROTOTYPE",
            env_doctor.environment_names(root, "backend"),
        )

    def test_combination_diagnostics_never_expose_values(self):
        checks = env_doctor.combination_checks(
            "backend",
            {
                "WORKER_ENABLED": "true",
                "AI_F2_PROVIDER_STATUS": "active",
                "AI_OPENAI_API_KEY": "private-marker",
                "AI_VLLM_SLLM_BASE_URL": "private-url-marker",
            },
        )
        text = json.dumps(checks, ensure_ascii=False)
        self.assertIn("ai/.env", text)
        self.assertNotIn("private-marker", text)
        self.assertNotIn("private-url-marker", text)

    def test_mode_origin_reports_only_allowlisted_values(self):
        with patch.dict(
            "os.environ", {"F3_ALLOW_SYNTHETIC_PROTOTYPE": "false"}, clear=True
        ):
            checks = env_doctor.mode_checks(
                "backend",
                {
                    "F3_ALLOW_SYNTHETIC_PROTOTYPE": "false",
                    "CHATBOT_ENABLED": "private-marker",
                },
                {"CHATBOT_ENABLED": "private-marker"},
            )
        text = json.dumps(checks, ensure_ascii=False)
        self.assertIn("process env", text)
        self.assertIn(".env", text)
        self.assertNotIn("private-marker", text)

    def test_commented_override_is_not_an_empty_assignment(self):
        self.assertEqual(
            env_doctor.entries("# AI_LLM_ENDPOINTS=[]\nWORKER_ENABLED=true # local\n"),
            {"WORKER_ENABLED": "true"},
        )

    def test_rename_preserves_bytes_and_never_interprets_shell(self):
        original = '# keep\r\nexport AI_VLLM_LLM_API_KEY="$(false) # private"\r\n'
        result, names = env_doctor.rewrite_names(original, env_doctor.RENAMES["ai"])
        self.assertEqual(
            result, original.replace("AI_VLLM_LLM_API_KEY", "AI_VLLM_SLLM_API_KEY")
        )
        self.assertNotIn("private", str(names))

    def test_collision_does_not_choose_a_secret(self):
        with self.assertRaises(ValueError):
            env_doctor.rewrite_names(
                "AI_VLLM_LLM_API_KEY=old\nAI_VLLM_SLLM_API_KEY=new\n",
                env_doctor.RENAMES["ai"],
            )

    def test_duplicate_legacy_key_fails(self):
        with self.assertRaises(ValueError):
            env_doctor.rewrite_names(
                "AI_VLLM_LLM_API_KEY=old\nAI_VLLM_LLM_API_KEY=new\n",
                env_doctor.RENAMES["ai"],
            )

    def test_multiline_secret_is_not_rewritten_as_an_assignment(self):
        original = 'PRIVATE="first\nAI_VLLM_LLM_API_KEY=part-of-secret\nlast"\n'
        with self.assertRaises(ValueError) as raised:
            env_doctor.rewrite_names(original, env_doctor.RENAMES["ai"])
        self.assertNotIn("part-of-secret", str(raised.exception))

    def test_fix_is_private_idempotent_and_does_not_copy_modules(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "ai").mkdir()
            path = root / "ai/.env"
            path.write_text("AI_VLLM_LLM_API_KEY=synthetic-private\n")
            with patch.object(env_doctor, "tracked", return_value=False):
                result = env_doctor.inspect(root, fix=True)
                second = env_doctor.inspect(root, fix=True)
            self.assertNotIn("synthetic-private", json.dumps(result + second))
            self.assertEqual(
                path.read_text(), "AI_VLLM_SLLM_API_KEY=synthetic-private\n"
            )
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertFalse((root / "backend/.env").exists())

    def test_symlink_and_tracked_file_are_not_modified(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "ai").mkdir()
            source = root / "private"
            source.write_text("keep")
            (root / "ai/.env").symlink_to(source)
            result = env_doctor.inspect(root, fix=True)
            self.assertEqual(result[0]["status"], "fail")
            self.assertEqual(source.read_text(), "keep")
            (root / "ai/.env").unlink()
            (root / "ai/.env").write_text("keep")
            with patch.object(env_doctor, "tracked", return_value=True):
                result = env_doctor.inspect(root, fix=True)
            self.assertEqual(result[0]["status"], "fail")


class PlanSafety(unittest.TestCase):
    def test_rejects_changed_inputs_changed_plan_expiry_and_unsealed_plan(self):
        with tempfile.TemporaryDirectory() as temporary:
            infra = Path(temporary)
            root = infra / "bootstrap"
            root.mkdir()
            plan = root / "bootstrap.tfplan"
            plan.write_bytes(b"plan")
            source = root / "main.tf"
            source.write_text("before")
            with self.assertRaises(ValueError):
                plan_guard.check(infra, plan)
            plan_guard.seal(infra, plan)
            plan_guard.check(infra, plan)
            self.assertEqual(stat.S_IMODE(plan.stat().st_mode), 0o600)
            source.write_text("after")
            with self.assertRaises(ValueError):
                plan_guard.check(infra, plan)
            source.write_text("before")
            plan.write_bytes(b"tampered")
            with self.assertRaises(ValueError):
                plan_guard.check(infra, plan)
            plan.write_bytes(b"plan")
            created = json.loads(plan.with_suffix(".plan-meta.json").read_text())[
                "created_at"
            ]
            with self.assertRaises(ValueError):
                plan_guard.check(infra, plan, now=created + plan_guard.MAX_AGE + 1)

    def test_auto_tfvars_changes_invalidate_plan_but_personal_env_is_never_hashed(self):
        with tempfile.TemporaryDirectory() as temporary:
            infra = Path(temporary)
            root = infra / "environments/dev"
            root.mkdir(parents=True)
            plan = root / "dev.tfplan"
            plan.write_bytes(b"plan")
            (root / ".env").write_text("SECRET=private")
            plan_guard.seal(infra, plan)
            self.assertNotIn(".env", plan.with_suffix(".plan-meta.json").read_text())
            (root / "capacity.auto.tfvars.json").write_text(
                '{"gpu_provisioned_workloads": ["f2"]}'
            )
            with self.assertRaises(ValueError):
                plan_guard.check(infra, plan)


class CloudSafety(unittest.TestCase):
    def test_doctor_uses_read_only_calls_and_never_reports_secret_values(self):
        class ReadOnlyAws:
            def call(self, service, action, *args):
                allowed = {
                    "describe-auto-scaling-groups",
                    "describe-db-instances",
                    "describe-volumes",
                    "list-distributions",
                    "describe-secret",
                    "list-pipeline-executions",
                }
                if action not in allowed:
                    raise AssertionError("Unexpected mutation: " + action)
                return {
                    "describe-auto-scaling-groups": {
                        "AutoScalingGroups": [{"DesiredCapacity": 0, "Instances": []}]
                    },
                    "describe-db-instances": {
                        "DBInstances": [
                            {"DBInstanceStatus": "stopped", "AllocatedStorage": 20}
                        ]
                    },
                    "describe-volumes": {"Volumes": []},
                    "list-distributions": {"DistributionList": {}},
                    "describe-secret": {"VersionIdsToStages": {"v1": ["AWSCURRENT"]}},
                    "list-pipeline-executions": {"pipelineExecutionSummaries": []},
                }[action]

            def secret(self, suffix):
                if suffix == "runpod/operator-api-key":
                    return "synthetic-operator-private"
                fields = operations.SECRET_FIELDS[suffix]
                return (
                    json.dumps(
                        {name: chr(97 + i) * 43 for i, name in enumerate(fields)}
                    )
                    if fields
                    else "synthetic-webhook-private"
                )

            def parameter(self, suffix):
                if suffix == "serving/SELECTION":
                    return {"f2": None, "general": None}
                return {"status": "offline"}

        get_runpod = Mock(return_value=[])
        result = operations.inspect_cloud(
            ReadOnlyAws(), ready=True, get_runpod=get_runpod
        )
        output = json.dumps(result)
        self.assertNotIn("synthetic-operator-private", output)
        self.assertNotIn("synthetic-webhook-private", output)
        self.assertNotIn("a" * 43, output)
        self.assertTrue(
            any(x["status"] == "fail" and x["target"] == "f2" for x in result)
        )
        self.assertEqual(get_runpod.call_args.args[1], "pods")

    def test_known_broken_or_incompatible_image_never_ready(self):
        for digest in operations.BROKEN_IMAGES:
            self.assertEqual(
                operations.image_check(
                    "ghcr.io/test/image@sha256:" + digest, "f2", None, {"images": []}
                )[0],
                "fail",
            )
        image = "ghcr.io/test/image@sha256:" + "a" * 64
        catalog = {
            "images": [{"image": image, "profiles": {"qwen": {"status": "failed"}}}]
        }
        self.assertEqual(
            operations.image_check(image, "general", "qwen", catalog)[0], "fail"
        )
        self.assertEqual(
            operations.image_check(image, "general", None, catalog)[0], "fail"
        )
        self.assertEqual(
            operations.image_check("ghcr.io/test/image:latest", "f2", None, catalog)[0],
            "fail",
        )

    def test_evaluation_never_reported_as_quality_approval(self):
        image = "ghcr.io/test/image@sha256:" + "a" * 64
        catalog = {
            "images": [{"image": image, "profiles": {"qwen": {"status": "evaluated"}}}]
        }
        state, message = operations.image_check(image, "general", "qwen", catalog)
        self.assertEqual(state, "warn")
        self.assertIn("품질 승인", message)

    def test_verify_offline_never_runs_or_starts_anything(self):
        aws = Mock()
        aws.call.return_value = {"AutoScalingGroups": [{"Instances": []}]}
        with patch.object(operations.subprocess, "run") as run:
            with self.assertRaises(operations.QueryError):
                operations.verify_running(aws, ["f2"], "123456789012", "profile")
            run.assert_not_called()

    def test_verify_requires_all_endpoints_before_any_inference(self):
        aws = Mock()
        aws.call.return_value = {
            "AutoScalingGroups": [{"Instances": [{"LifecycleState": "InService"}]}]
        }
        aws.parameter.side_effect = [{"status": "active"}, {"status": "offline"}]
        with patch.object(operations.subprocess, "run") as run:
            with self.assertRaises(operations.QueryError):
                operations.verify_running(
                    aws, ["f2", "general"], "123456789012", "profile"
                )
            run.assert_not_called()

    def test_verify_only_calls_existing_smoke_and_hides_provider_output(self):
        aws = Mock()
        aws.call.return_value = {
            "AutoScalingGroups": [{"Instances": [{"LifecycleState": "InService"}]}]
        }
        aws.parameter.return_value = {"status": "active"}
        with patch.object(
            operations.subprocess,
            "run",
            return_value=Mock(returncode=1, stdout="private", stderr="private"),
        ) as run:
            result = operations.verify_running(aws, ["f2"], "123456789012", "profile")
            self.assertEqual(run.call_args.args[0][-2:], ["smoke", "f2"])
            self.assertNotIn("private", json.dumps(result))
            self.assertEqual(result[0]["status"], "fail")

    def test_aws_error_body_is_not_reported(self):
        aws = operations.Aws.__new__(operations.Aws)
        aws.env = {}
        aws.profile = "test"
        with patch.object(
            operations.subprocess,
            "run",
            return_value=Mock(returncode=1, stderr="private-key", stdout="private-url"),
        ):
            with self.assertRaises(operations.QueryError) as caught:
                aws.call("ssm", "get-parameter")
            self.assertNotIn("private", str(caught.exception))


class ReleaseSafety(unittest.TestCase):
    def test_gpu_import_rejects_secret_and_capacity_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "profiles.json"
            source.write_text('{"gpu_profiles": {}, "secret": "private"}')
            with self.assertRaises(ValueError):
                release_tools.adopt_gpu_profiles(source)

    def test_new_model_keeps_internal_id_and_never_claims_live_validation(self):
        catalog = json.loads(release_tools.CATALOG.read_text())
        new = next(
            x for x in catalog["releases"] if x["release_id"] == "consultation-v3"
        )
        self.assertEqual(new["release_stage"], "verified")
        self.assertEqual(new["serving_validation"], "pending-user-startup-check")
        self.assertEqual(
            new["source_filename"], "f2-consultation-v05-qwen3-4b-v2.tar.gz"
        )


if __name__ == "__main__":
    unittest.main()
