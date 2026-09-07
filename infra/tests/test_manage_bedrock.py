import importlib.util
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "infra/scripts/manage_bedrock.py"
SPEC = importlib.util.spec_from_file_location("manage_bedrock", PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class FakeSession:
    def __init__(self, ec2_response: dict | None = None):
        self.ec2 = FakeEc2(ec2_response or {})
        self.ssm = FakeSsm()

    def client(self, name: str):
        return {"ec2": self.ec2, "ssm": self.ssm}[name]


class FakeEc2:
    def __init__(self, response: dict):
        self.response = response
        self.request: dict | None = None

    def describe_instances(self, **kwargs):
        self.request = kwargs
        return self.response


class FakeSsm:
    def __init__(self):
        self.sent: dict | None = None

    def describe_instance_information(self, **_kwargs):
        return {"InstanceInformationList": [{"PingStatus": "Online"}]}

    def send_command(self, **kwargs):
        self.sent = kwargs
        return {"Command": {"CommandId": "command-1"}}

    def get_command_invocation(self, **_kwargs):
        return {
            "Status": "Success",
            "StandardOutputContent": MODULE.SUCCESS_MARKER,
        }


def instance_response(
    *, hop_limit: int = 2, tokens: str = "required", state: str = "applied"
) -> dict:
    return {
        "Reservations": [
            {
                "Instances": [
                    {
                        "InstanceId": "i-0123456789abcdef0",
                        "MetadataOptions": {
                            "State": state,
                            "HttpTokens": tokens,
                            "HttpPutResponseHopLimit": hop_limit,
                        },
                    }
                ]
            }
        ]
    }


class BedrockDoctorTests(unittest.TestCase):
    def settings(self) -> object:
        return MODULE.Settings(
            account_id="123456789012",
            profile="skn30-session",
            region="ap-northeast-2",
            project="skn30-final-3team",
            operator_role="TerraformOperatorRole",
        )

    def test_container_check_is_read_only_and_uses_instance_role(self) -> None:
        command = MODULE.container_doctor_command("ap-northeast-2")

        self.assertIn("get_inference_profile", command)
        self.assertIn(MODULE.BEDROCK_PROFILE_ID, command)
        self.assertIn("compose run --rm --no-deps worker", command)
        self.assertNotIn("invoke_model", command)
        self.assertNotIn("/responses", command)
        self.assertNotIn("API_KEY", command)

    def test_instance_requires_imdsv2_token_and_two_hops(self) -> None:
        settings = self.settings()
        session = FakeSession(instance_response())
        self.assertEqual(
            MODULE.find_app_instance(session, settings),
            "i-0123456789abcdef0",
        )
        self.assertIn(
            {
                "Name": "tag:aws:autoscaling:groupName",
                "Values": ["skn30-final-3team-dev-app"],
            },
            session.ec2.request["Filters"],
        )
        for response in (
            instance_response(hop_limit=1),
            instance_response(tokens="optional"),
            instance_response(state="pending"),
            {"Reservations": []},
        ):
            with self.subTest(response=response), self.assertRaises(MODULE.ToolError):
                MODULE.find_app_instance(FakeSession(response), settings)

    def test_doctor_emits_only_safe_logical_result(self) -> None:
        session = FakeSession(instance_response())
        output = io.StringIO()

        with redirect_stdout(output), patch.object(MODULE.time, "sleep"):
            MODULE.doctor(session, self.settings())

        event = json.loads(output.getvalue())
        self.assertEqual(event["event"], "bedrock-doctor-complete")
        self.assertEqual(event["authentication"], "ec2-instance-role-sigv4")
        self.assertFalse(event["inference"])
        self.assertNotIn("i-0123456789abcdef0", output.getvalue())
        assert session.ssm.sent is not None
        self.assertEqual(session.ssm.sent["DocumentName"], "AWS-RunShellScript")

    def test_settings_reject_wrong_account_and_region(self) -> None:
        parser = MODULE.parser()
        for arguments in (
            ["--account-id", "123"],
            [
                "--account-id",
                "123456789012",
                "--region",
                "us-east-1",
            ],
        ):
            with self.subTest(arguments=arguments), self.assertRaises(MODULE.ToolError):
                MODULE.settings_from(parser.parse_args(arguments))


if __name__ == "__main__":
    unittest.main()
