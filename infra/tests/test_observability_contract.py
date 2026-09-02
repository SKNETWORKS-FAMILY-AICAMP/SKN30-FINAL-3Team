import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def read(relative_path: str) -> str:
    return (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")


def section(source: str, start: str, end: str) -> str:
    start_index = source.index(start)
    return source[start_index : source.index(end, start_index)]


class ObservabilityContractTests(unittest.TestCase):
    def test_delivery_notifier_route_is_preserved_and_alarm_route_is_separate(
        self,
    ) -> None:
        observability = read("infra/environments/dev/observability.tf")
        delivery = read("infra/environments/dev/delivery.tf")

        self.assertIn(
            'source_file = "${path.module}/../../delivery/lambda/discord_notifier.py"',
            delivery,
        )
        self.assertIn("topic_arn = aws_sns_topic.runtime_alerts.arn", delivery)
        self.assertIn(
            'source_file = "${path.module}/../../delivery/lambda/cloudwatch_alarm_notifier.py"',
            observability,
        )
        self.assertIn("topic_arn = aws_sns_topic.cloudwatch_alarms.arn", observability)
        self.assertNotIn(
            "aws_sns_topic.runtime_alerts.arn]",
            observability.split('resource "aws_cloudwatch_metric_alarm"', maxsplit=1)[
                1
            ],
        )

    def test_alarm_webhook_is_an_external_value_container(self) -> None:
        observability = read("infra/environments/dev/observability.tf")

        self.assertNotIn("secret_string", observability)
        self.assertIn(
            'name                    = "/${local.name_prefix}/observability/alarm-discord-webhook"',
            observability,
        )
        self.assertNotIn("aws_secretsmanager_secret.discord_webhook.arn", observability)
        self.assertIn(
            "from = aws_secretsmanager_secret_version.alarm_discord_webhook",
            observability,
        )
        self.assertIn("destroy = false", observability)

    def test_alarm_notifier_has_precreated_logs_and_minimum_permissions(self) -> None:
        observability = read("infra/environments/dev/observability.tf")
        log_group = section(
            observability,
            'resource "aws_cloudwatch_log_group" "cloudwatch_alarm_notifier"',
            'resource "aws_iam_role" "cloudwatch_alarm_notifier"',
        )
        policy = section(
            observability,
            'resource "aws_iam_role_policy" "cloudwatch_alarm_notifier"',
            'resource "aws_lambda_function" "cloudwatch_alarm_notifier"',
        )

        self.assertIn("retention_in_days = 14", log_group)
        self.assertIn('"logs:CreateLogStream"', policy)
        self.assertIn('"logs:PutLogEvents"', policy)
        self.assertNotIn('"logs:CreateLogGroup"', policy)
        self.assertIn('"secretsmanager:GetSecretValue"', policy)
        self.assertIn('"logs:StartQuery"', policy)
        self.assertIn('"logs:GetQueryResults"', policy)
        self.assertIn('"logs:StopQuery"', policy)
        self.assertIn('aws_cloudwatch_log_group.runtime["api"].arn', policy)
        self.assertIn('aws_cloudwatch_log_group.runtime["worker"].arn', policy)
        self.assertEqual(policy.count('Resource = "*"'), 1)
        self.assertNotIn("codepipeline:", policy)
        self.assertNotIn("codedeploy:", policy)

    def test_alarm_enrichment_uses_exact_module_mappings_and_runbook(self) -> None:
        observability = read("infra/environments/dev/observability.tf")
        locals_block = section(
            observability,
            "locals {",
            'resource "aws_cloudwatch_log_group" "runtime"',
        )
        notifier = section(
            observability,
            'resource "aws_lambda_function" "cloudwatch_alarm_notifier"',
            'resource "aws_lambda_permission" "cloudwatch_alarms"',
        )

        self.assertIn('"${local.name_prefix}-backend-unhandled-errors"', locals_block)
        self.assertIn('"${local.name_prefix}-ai-terminal-failures"', locals_block)
        self.assertIn('module          = "backend"', locals_block)
        self.assertIn('module = "ai"', locals_block)
        self.assertIn('event           = "unhandled_request_error"', locals_block)
        self.assertIn('event  = "ai_terminal_failure"', locals_block)
        self.assertIn('aws_cloudwatch_log_group.runtime["api"].name', locals_block)
        self.assertIn('aws_cloudwatch_log_group.runtime["worker"].name', locals_block)
        self.assertIn(
            "ALARM_LOG_CONTEXTS_JSON  = jsonencode(local.alarm_log_contexts)",
            notifier,
        )
        self.assertIn("ALARM_RUNBOOK_URL        = local.alarm_runbook_url", notifier)

    def test_cloudwatch_topic_policy_limits_alarm_publishers(self) -> None:
        observability = read("infra/environments/dev/observability.tf")
        topic_policy = section(
            observability,
            'data "aws_iam_policy_document" "cloudwatch_alarms_topic"',
            'resource "aws_sns_topic_policy" "cloudwatch_alarms"',
        )

        self.assertIn('identifiers = ["cloudwatch.amazonaws.com"]', topic_policy)
        self.assertIn('variable = "aws:SourceAccount"', topic_policy)
        self.assertIn('variable = "aws:SourceArn"', topic_policy)
        self.assertIn("alarm:${local.name_prefix}-*", topic_policy)

    def test_backend_and_ai_filters_publish_dimensionless_count_metrics(self) -> None:
        observability = read("infra/environments/dev/observability.tf")
        backend_filter = section(
            observability,
            'resource "aws_cloudwatch_log_metric_filter" "backend_unhandled_error"',
            'resource "aws_cloudwatch_log_metric_filter" "ai_terminal_failure_api"',
        )
        ai_api_filter = section(
            observability,
            'resource "aws_cloudwatch_log_metric_filter" "ai_terminal_failure_api"',
            'resource "aws_cloudwatch_log_metric_filter" "ai_terminal_failure_worker"',
        )
        ai_worker_filter = section(
            observability,
            'resource "aws_cloudwatch_log_metric_filter" "ai_terminal_failure_worker"',
            'resource "aws_cloudwatch_metric_alarm" "backend_unhandled_errors"',
        )

        self.assertIn(
            'pattern        = "{ $.event = \\"unhandled_request_error\\" }"',
            backend_filter,
        )
        self.assertIn(
            'log_group_name = aws_cloudwatch_log_group.runtime["api"].name',
            backend_filter,
        )
        for filter_config, group in (
            (ai_api_filter, "api"),
            (ai_worker_filter, "worker"),
        ):
            self.assertIn(
                'pattern        = "{ $.event = \\"ai_terminal_failure\\" }"',
                filter_config,
            )
            self.assertIn(
                f'log_group_name = aws_cloudwatch_log_group.runtime["{group}"].name',
                filter_config,
            )
            self.assertNotIn("dimensions", filter_config)

        self.assertIn('name      = "BackendUnhandledErrorCount"', backend_filter)
        self.assertIn('name      = "AiTerminalFailureCount"', ai_api_filter)
        self.assertIn('name      = "AiTerminalFailureCount"', ai_worker_filter)
        self.assertNotIn("dimensions", backend_filter)
        for filter_config in (backend_filter, ai_api_filter, ai_worker_filter):
            self.assertNotIn("default_value", filter_config)

    def test_all_alarms_use_the_alarm_topic_and_app_thresholds_are_minimal(
        self,
    ) -> None:
        observability = read("infra/environments/dev/observability.tf")
        runpod_observability = read(
            "infra/environments/dev/runpod-observability.tf"
        )

        self.assertEqual(
            observability.count(
                "alarm_actions = [aws_sns_topic.cloudwatch_alarms.arn]"
            ),
            8,
        )
        self.assertEqual(
            observability.count(
                "ok_actions    = [aws_sns_topic.cloudwatch_alarms.arn]"
            ),
            8,
        )
        self.assertEqual(
            runpod_observability.count(
                "alarm_actions = [aws_sns_topic.cloudwatch_alarms.arn]"
            ),
            3,
        )
        self.assertEqual(
            runpod_observability.count(
                "ok_actions    = [aws_sns_topic.cloudwatch_alarms.arn]"
            ),
            3,
        )
        for start, end in (
            (
                'resource "aws_cloudwatch_metric_alarm" "backend_unhandled_errors"',
                'resource "aws_cloudwatch_metric_alarm" "ai_terminal_failures"',
            ),
            (
                'resource "aws_cloudwatch_metric_alarm" "ai_terminal_failures"',
                'resource "aws_cloudwatch_metric_alarm" "alb_unhealthy_hosts"',
            ),
        ):
            alarm = section(observability, start, end)
            self.assertIn("period              = 300", alarm)
            self.assertIn("evaluation_periods  = 1", alarm)
            self.assertIn("datapoints_to_alarm = 1", alarm)
            self.assertIn("threshold           = 1", alarm)
            self.assertIn('treat_missing_data  = "notBreaching"', alarm)

    def test_runpod_monitor_is_read_only_and_uses_project_metrics(self) -> None:
        source = read("infra/environments/dev/runpod-observability.tf")
        variables = read("infra/environments/dev/variables.tf")
        policy = section(
            source,
            'resource "aws_iam_role_policy" "runpod_monitor"',
            'resource "aws_lambda_function" "runpod_monitor"',
        )

        for allowed in (
            '"secretsmanager:GetSecretValue"',
            '"ssm:GetParameter"',
            '"cloudwatch:PutMetricData"',
            '"logs:CreateLogStream"',
            '"logs:PutLogEvents"',
        ):
            self.assertIn(allowed, policy)
        for forbidden in (
            "ssm:PutParameter",
            "ssm:SendCommand",
            "ec2:TerminateInstances",
            "runpod:",
        ):
            self.assertNotIn(forbidden, policy)
        self.assertIn('"cloudwatch:namespace" = local.runtime_metric_namespace', policy)
        self.assertIn(
            'schedule_expression = "rate(${var.runpod_monitor_interval_minutes} minutes)"',
            source,
        )
        self.assertIn('variable "runpod_monitor_interval_minutes"', variables)
        self.assertIn('variable "runpod_runtime_warning_hours"', variables)
        for metric in (
            "RunPodMonitorHeartbeat",
            "RunPodControlPlaneReachable",
            "RunPodEndpointConsistent",
            "RunPodSllmHealthy",
            "RunPodSttHealthy",
            "RunPodOrphanPodAgeMinutes",
            "RunPodRuntimeHours",
        ):
            self.assertIn(metric, source)


if __name__ == "__main__":
    unittest.main()
