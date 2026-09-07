import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


class BedrockInfraContractTests(unittest.TestCase):
    def test_public_endpoint_address_book_has_no_secret(self) -> None:
        configuration = read("infra/environments/dev/configuration.tf")

        self.assertIn("AI_LLM_ENDPOINTS = jsonencode([", configuration)
        self.assertIn('alias      = "general-dev-bedrock"', configuration)
        self.assertIn('provider   = "bedrock"', configuration)
        self.assertIn("aws_region = var.aws_region", configuration)
        self.assertNotIn("AI_BEDROCK_API_KEY", configuration)

    def test_runtime_role_is_luna_only_and_non_streaming(self) -> None:
        runtime = read("infra/environments/dev/runtime.tf")

        for value in (
            'bedrock_luna_model_id    = "openai.gpt-5.6-luna"',
            'bedrock_luna_profile_id  = "global.${local.bedrock_luna_model_id}"',
            "inference-profile/${local.bedrock_luna_profile_id}",
            "foundation-model/${local.bedrock_luna_model_id}",
            "arn:aws:bedrock:::foundation-model/${local.bedrock_luna_model_id}",
            "project/default",
            'variable = "bedrock:InferenceProfileArn"',
            'variable = "bedrock:ProjectArn"',
            'variable = "bedrock:ModelArn"',
            'values   = ["unspecified"]',
            'actions   = ["bedrock:GetInferenceProfile"]',
            'actions   = ["bedrock:InvokeModel"]',
        ):
            self.assertIn(value, runtime)
        self.assertNotIn("bedrock:InvokeModelWithResponseStream", runtime)
        self.assertNotIn("AmazonBedrockFullAccess", runtime)
        self.assertNotIn("bedrock:*", runtime)

    def test_container_credentials_use_required_imdsv2_with_two_hops(self) -> None:
        runtime = read("infra/environments/dev/runtime.tf")

        self.assertIn('http_endpoint               = "enabled"', runtime)
        self.assertIn('http_tokens                 = "required"', runtime)
        self.assertIn("http_put_response_hop_limit = 2", runtime)

    def test_shared_dev_seed_requires_explicit_bedrock_profile(self) -> None:
        justfile = read("infra/justfile")
        db_access = read("infra/scripts/manage_db_access.py")

        self.assertIn(
            "seed-f3 --model-profile dev-bedrock-gpt56-luna --apply",
            justfile,
        )
        self.assertIn(
            "seed-f3 --model-profile local-openai --apply",
            justfile,
        )
        self.assertIn('"dev-bedrock-gpt56-luna"', db_access)
        self.assertIn("30개 검증", justfile)

    def test_existing_instance_must_be_replaced_before_doctor(self) -> None:
        runtime = read("infra/environments/dev/runtime.tf")
        operations = read("docs/architecture/infra/deployment-and-operations.md")

        self.assertNotIn("instance_refresh {", runtime)
        stop_position = operations.index("`just dev-stop`")
        start_position = operations.index("`just dev-start`", stop_position)
        doctor_position = operations.index("`just bedrock-doctor`", start_position)
        seed_position = operations.index("`just dev-seed-f3`", doctor_position)
        self.assertLess(stop_position, start_position)
        self.assertLess(start_position, doctor_position)
        self.assertLess(doctor_position, seed_position)


if __name__ == "__main__":
    unittest.main()
