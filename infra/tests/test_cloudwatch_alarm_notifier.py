import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE = (
    REPOSITORY_ROOT
    / "infra/delivery/lambda/cloudwatch_alarm_notifier.py"
)
FIXTURE = (
    REPOSITORY_ROOT
    / "infra/tests/fixtures/cloudwatch_alarm_sns_message.json"
)


def load_module():
    spec = importlib.util.spec_from_file_location("cloudwatch_alarm_notifier", SOURCE)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load CloudWatch alarm notifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Response:
    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None


class CloudWatchAlarmNotifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()
        self.message = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.event = {"Records": [{"Sns": {"Message": json.dumps(self.message)}}]}
        self.module._secretsmanager = Mock()
        self.module._secretsmanager.get_secret_value.return_value = {
            "SecretString": "https://discord.com/api/webhooks/synthetic/test"
        }
        environment = patch.dict(
            self.module.os.environ,
            {"ALARM_DISCORD_SECRET_ARN": "synthetic-alarm-webhook-secret"},
        )
        environment.start()
        self.addCleanup(environment.stop)

    def test_standard_alarm_fixture_includes_required_fields(self) -> None:
        with patch.object(
            self.module.urllib.request,
            "urlopen",
            return_value=Response(204),
        ) as urlopen:
            self.module.handler(self.event, None)

        request = urlopen.call_args.args[0]
        body = json.loads(request.data.decode())
        self.assertIn(self.message["AlarmName"], body["content"])
        self.assertIn(self.message["NewStateValue"], body["content"])
        self.assertIn(self.message["NewStateReason"], body["content"])
        self.assertLessEqual(len(body["content"]), 2_000)
        self.assertEqual(body["allowed_mentions"], {"parse": []})
        self.module._secretsmanager.get_secret_value.assert_called_once()

    def test_long_reason_is_truncated_to_discord_limit(self) -> None:
        self.message["NewStateReason"] = "failure " * 1_000

        content = self.module.alarm_message(self.message)

        self.assertIsNotNone(content)
        self.assertEqual(len(content), 2_000)
        self.assertTrue(content.endswith("…"))
        self.assertIn("alarm name:", content)
        self.assertIn("state:", content)
        self.assertIn("reason:", content)

    def test_malformed_and_incomplete_records_are_ignored(self) -> None:
        event = {
            "Records": [
                None,
                {},
                {"Sns": {"Message": "not-json"}},
                {"Sns": {"Message": json.dumps([])}},
                {"Sns": {"Message": json.dumps({"AlarmName": "missing"})}},
            ]
        }

        with patch.object(self.module.urllib.request, "urlopen") as urlopen:
            self.module.handler(event, None)

        urlopen.assert_not_called()
        self.module._secretsmanager.get_secret_value.assert_not_called()

    def test_discord_http_error_is_raised_for_sns_retry(self) -> None:
        with patch.object(
            self.module.urllib.request,
            "urlopen",
            return_value=Response(503),
        ), self.assertRaisesRegex(RuntimeError, "Discord returned HTTP 503"):
            self.module.handler(self.event, None)


if __name__ == "__main__":
    unittest.main()
