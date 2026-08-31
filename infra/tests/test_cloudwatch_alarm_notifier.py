import importlib.util
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import unquote

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE = REPOSITORY_ROOT / "infra/delivery/lambda/cloudwatch_alarm_notifier.py"
FIXTURE = REPOSITORY_ROOT / "infra/tests/fixtures/cloudwatch_alarm_sns_message.json"


def load_module():
    spec = importlib.util.spec_from_file_location("cloudwatch_alarm_notifier", SOURCE)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load CloudWatch alarm notifier")
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"boto3": Mock()}):
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
        self.module._logs = Mock()
        self.module._logs.start_query.return_value = {"queryId": "query-1"}
        self.module._logs.get_query_results.return_value = {
            "status": "Complete",
            "results": [
                [
                    {"field": "@timestamp", "value": "2026-08-31T00:04:59.000Z"},
                    {"field": "source", "value": "f2"},
                    {
                        "field": "request_id",
                        "value": "8ec9ba86-79ef-4aba-b211-6838a37f7952",
                    },
                    {"field": "status_code", "value": "500"},
                    {"field": "error_type", "value": "RuntimeError"},
                    {
                        "field": "error_location",
                        "value": "backend.src.main:handler:100",
                    },
                    {"field": "@ptr", "value": "private-pointer"},
                    {"field": "message", "value": "private exception message"},
                ]
            ],
        }
        contexts = {
            self.message["AlarmName"]: {
                "module": "backend",
                "event": "unhandled_request_error",
                "log_group_names": ["/skn30-final-3team-dev/application/api"],
            },
            "skn30-final-3team-dev-ai-terminal-failures": {
                "module": "ai",
                "event": "ai_terminal_failure",
                "log_group_names": [
                    "/skn30-final-3team-dev/application/api",
                    "/skn30-final-3team-dev/application/worker",
                ],
            },
        }
        environment = patch.dict(
            self.module.os.environ,
            {
                "ALARM_DISCORD_SECRET_ARN": "synthetic-alarm-webhook-secret",
                "ALARM_LOG_CONTEXTS_JSON": json.dumps(contexts),
                "ALARM_RUNBOOK_URL": (
                    "https://github.com/SKNETWORKS-FAMILY-AICAMP/"
                    "SKN30-FINAL-3Team/blob/dev/docs/operations/"
                    "cloudwatch-alarm-response.md"
                ),
                "AWS_REGION": "ap-northeast-2",
            },
        )
        environment.start()
        self.addCleanup(environment.stop)

    def _deliver(self) -> tuple[str, Mock]:
        with patch.object(
            self.module.urllib.request,
            "urlopen",
            return_value=Response(204),
        ) as urlopen:
            self.module.handler(self.event, None)
        request = urlopen.call_args.args[0]
        body = json.loads(request.data.decode())
        return body["content"], urlopen

    def test_application_alarm_includes_stable_module_links_and_safe_detail(
        self,
    ) -> None:
        content, urlopen = self._deliver()

        self.assertIn(self.message["AlarmName"], content)
        self.assertIn("module: backend", content)
        self.assertIn(self.message["NewStateValue"], content)
        self.assertIn(self.message["NewStateReason"], content)
        self.assertIn("changed at: 2026-08-31T00:05:00.000Z", content)
        self.assertIn("[Alarm](https://ap-northeast-2.console.aws.amazon.com", content)
        self.assertIn(
            "[Logs Insights](https://ap-northeast-2.console.aws.amazon.com", content
        )
        self.assertIn("[Runbook](https://github.com/", content)
        self.assertNotIn("Asia Pacific (Seoul)", content)
        self.assertIn("not confirmed as root cause", content)
        self.assertIn("source: f2", content)
        self.assertIn("request_id: 8ec9ba86-79ef-4aba-b211-6838a37f7952", content)
        self.assertIn("error_type: RuntimeError", content)
        self.assertNotIn("private-pointer", content)
        self.assertNotIn("private exception message", content)
        self.assertLessEqual(len(content), 2_000)

        query = self.module._logs.start_query.call_args.kwargs
        self.assertEqual(
            query["logGroupNames"],
            ["/skn30-final-3team-dev/application/api"],
        )
        self.assertEqual(query["limit"], 1)
        self.assertIn('filter event = "unhandled_request_error"', query["queryString"])
        self.assertIn(
            "fields @timestamp, source, request_id, run_id", query["queryString"]
        )
        expected = datetime(2026, 8, 31, 0, 5, tzinfo=timezone.utc)
        self.assertEqual(query["startTime"], int(expected.timestamp()) - 600)
        self.assertEqual(query["endTime"], int(expected.timestamp()) + 600)
        self.assertEqual(
            json.loads(urlopen.call_args.args[0].data.decode())["allowed_mentions"],
            {"parse": []},
        )
        self.module._secretsmanager.get_secret_value.assert_called_once()
        self.module._logs.get_log_record.assert_not_called()

    def test_ai_alarm_queries_api_and_worker_without_routing_on_source(self) -> None:
        alarm_name = "skn30-final-3team-dev-ai-terminal-failures"
        self.message["AlarmName"] = alarm_name
        self.message["AlarmArn"] = (
            "arn:aws:cloudwatch:ap-northeast-2:000000000000:alarm:" + alarm_name
        )
        self.event["Records"][0]["Sns"]["Message"] = json.dumps(self.message)

        content, _ = self._deliver()

        self.assertIn("module: ai", content)
        self.assertEqual(
            self.module._logs.start_query.call_args.kwargs["logGroupNames"],
            [
                "/skn30-final-3team-dev/application/api",
                "/skn30-final-3team-dev/application/worker",
            ],
        )
        self.assertIn(
            'filter event = "ai_terminal_failure"',
            self.module._logs.start_query.call_args.kwargs["queryString"],
        )

    def test_logs_insights_link_preserves_absolute_window_query_and_groups(
        self,
    ) -> None:
        start_time = datetime(2026, 8, 30, 23, 55, tzinfo=timezone.utc)
        end_time = datetime(2026, 8, 31, 0, 15, tzinfo=timezone.utc)
        query = self.module._query_string("ai_terminal_failure")

        url = self.module._logs_insights_url(
            "ap-northeast-2",
            (
                "/skn30-final-3team-dev/application/api",
                "/skn30-final-3team-dev/application/worker",
            ),
            query,
            start_time,
            end_time,
        )

        route = url.split("#logsV2:logs-insights", maxsplit=1)[1]
        query_detail = unquote(route.replace("$", "%"))
        state = unquote(query_detail.split("=", maxsplit=1)[1])
        decoded_state = unquote(state.replace("*", "%"))
        self.assertIn("2026-08-30T23:55:00.000Z", decoded_state)
        self.assertIn("2026-08-31T00:15:00.000Z", decoded_state)
        self.assertIn('filter event = "ai_terminal_failure"', decoded_state)
        self.assertIn("/skn30-final-3team-dev/application/api", decoded_state)
        self.assertIn("/skn30-final-3team-dev/application/worker", decoded_state)

    def test_ok_application_alarm_has_links_but_does_not_start_query(self) -> None:
        self.message["NewStateValue"] = "OK"
        self.event["Records"][0]["Sns"]["Message"] = json.dumps(self.message)

        content, _ = self._deliver()

        self.assertIn("state: OK", content)
        self.assertIn("[Alarm]", content)
        self.assertIn("[Logs Insights]", content)
        self.assertIn("[Runbook]", content)
        self.assertNotIn("recent matching error", content)
        self.module._logs.start_query.assert_not_called()

    def test_infrastructure_and_unknown_alarm_names_do_not_query_logs(self) -> None:
        for alarm_name in (
            "skn30-final-3team-dev-asg-in-service-capacity",
            "skn30-final-3team-dev-backend-unhandled-errors-copy",
        ):
            with self.subTest(alarm_name=alarm_name):
                self.module._logs.reset_mock()
                self.message["AlarmName"] = alarm_name
                self.message["AlarmArn"] = (
                    "arn:aws:cloudwatch:ap-northeast-2:000000000000:alarm:" + alarm_name
                )
                self.event["Records"][0]["Sns"]["Message"] = json.dumps(self.message)

                content, _ = self._deliver()

                self.assertIn("module: infra", content)
                self.assertIn("[Alarm]", content)
                self.assertIn("[Runbook]", content)
                self.assertNotIn("[Logs Insights]", content)
                self.module._logs.start_query.assert_not_called()

    def test_invalid_alarm_arn_keeps_base_notification_without_links_or_query(
        self,
    ) -> None:
        self.message["AlarmArn"] = self.message["AlarmArn"].replace(
            "ap-northeast-2", "us-east-1"
        )
        self.event["Records"][0]["Sns"]["Message"] = json.dumps(self.message)

        content, _ = self._deliver()

        self.assertIn("module: backend", content)
        self.assertIn("reason:", content)
        self.assertNotIn("links:", content)
        self.module._logs.start_query.assert_not_called()

    def test_logs_query_failure_is_best_effort_and_does_not_expose_exception(
        self,
    ) -> None:
        self.module._logs.start_query.side_effect = RuntimeError(
            "provider secret exception detail"
        )

        with self.assertLogs(self.module.logger, level="WARNING") as captured:
            content, _ = self._deliver()

        self.assertIn("[Logs Insights]", content)
        self.assertNotIn("recent matching error", content)
        self.assertIn("QUERY_START_FAILED", " ".join(captured.output))
        self.assertNotIn("provider secret exception detail", " ".join(captured.output))

    def test_query_wait_timeout_stops_query_and_still_sends_base_message(self) -> None:
        self.module._logs.get_query_results.return_value = {"status": "Running"}

        with (
            patch.object(
                self.module.time,
                "monotonic",
                side_effect=[0.0, 0.1, 2.1, 2.1],
            ),
            patch.object(self.module.time, "sleep"),
            self.assertLogs(self.module.logger, level="WARNING") as captured,
        ):
            content, _ = self._deliver()

        self.module._logs.stop_query.assert_called_once_with(queryId="query-1")
        self.assertIn("QUERY_WAIT_TIMEOUT", " ".join(captured.output))
        self.assertIn("[Logs Insights]", content)
        self.assertNotIn("recent matching error", content)

    def test_stop_query_failure_is_swallowed_without_logging_aws_error(self) -> None:
        self.module._logs.get_query_results.return_value = {"status": "Running"}
        self.module._logs.stop_query.side_effect = RuntimeError(
            "sensitive AWS exception detail"
        )

        with (
            patch.object(
                self.module.time,
                "monotonic",
                side_effect=[0.0, 0.1, 2.1, 2.1],
            ),
            patch.object(self.module.time, "sleep"),
            self.assertLogs(self.module.logger, level="WARNING") as captured,
        ):
            content, _ = self._deliver()

        logged = " ".join(captured.output)
        self.assertIn("QUERY_STOP_FAILED", logged)
        self.assertIn("QUERY_WAIT_TIMEOUT", logged)
        self.assertNotIn("sensitive AWS exception detail", logged)
        self.assertIn("[Logs Insights]", content)

    def test_empty_query_result_keeps_base_message_and_links(self) -> None:
        self.module._logs.get_query_results.return_value = {
            "status": "Complete",
            "results": [],
        }

        with self.assertLogs(self.module.logger, level="WARNING") as captured:
            content, _ = self._deliver()

        self.assertIn("QUERY_NO_SAFE_RESULT", " ".join(captured.output))
        self.assertIn("[Logs Insights]", content)
        self.assertNotIn("recent matching error", content)

    def test_long_reason_and_detail_do_not_truncate_investigation_links(self) -> None:
        self.message["NewStateReason"] = "failure " * 1_000
        self.event["Records"][0]["Sns"]["Message"] = json.dumps(self.message)

        content, _ = self._deliver()

        self.assertLessEqual(len(content), 2_000)
        self.assertIn("[Alarm](https://", content)
        self.assertIn("[Logs Insights](https://", content)
        self.assertIn("[Runbook](https://", content)
        self.assertIn("reason:", content)
        self.assertTrue("failure" in content)

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
        self.module._logs.start_query.assert_not_called()

    def test_discord_http_error_is_raised_for_sns_retry(self) -> None:
        with (
            patch.object(
                self.module.urllib.request,
                "urlopen",
                return_value=Response(503),
            ),
            self.assertRaisesRegex(RuntimeError, "Discord returned HTTP 503"),
        ):
            self.module.handler(self.event, None)


if __name__ == "__main__":
    unittest.main()
