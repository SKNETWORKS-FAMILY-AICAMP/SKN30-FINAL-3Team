locals {
  runpod_monitor_period_seconds = var.runpod_monitor_interval_minutes * 60
  runpod_custom_alarms = {
    control_plane_unreachable = {
      alarm_name          = "${local.name_prefix}-runpod-control-plane-unreachable"
      description         = "RunPod read-only control-plane request failed twice consecutively"
      metric_name         = "RunPodControlPlaneReachable"
      comparison_operator = "LessThanThreshold"
      threshold           = 1
      evaluation_periods  = 2
      datapoints_to_alarm = 2
      treat_missing_data  = "missing"
    }
    endpoint_mismatch = {
      alarm_name          = "${local.name_prefix}-runpod-endpoint-mismatch"
      description         = "The active endpoint Pod ID does not match the single shared RunPod Pod"
      metric_name         = "RunPodEndpointConsistent"
      comparison_operator = "LessThanThreshold"
      threshold           = 1
      evaluation_periods  = 1
      datapoints_to_alarm = 1
      treat_missing_data  = "missing"
    }
    sllm_unhealthy = {
      alarm_name          = "${local.name_prefix}-runpod-sllm-unhealthy"
      description         = "Authenticated SLLM models health failed twice consecutively"
      metric_name         = "RunPodSllmHealthy"
      comparison_operator = "LessThanThreshold"
      threshold           = 1
      evaluation_periods  = 2
      datapoints_to_alarm = 2
      treat_missing_data  = "missing"
    }
    stt_unhealthy = {
      alarm_name          = "${local.name_prefix}-runpod-stt-unhealthy"
      description         = "Authenticated STT models health failed twice consecutively"
      metric_name         = "RunPodSttHealthy"
      comparison_operator = "LessThanThreshold"
      threshold           = 1
      evaluation_periods  = 2
      datapoints_to_alarm = 2
      treat_missing_data  = "missing"
    }
    offline_orphan = {
      alarm_name          = "${local.name_prefix}-runpod-offline-orphan"
      description         = "A shared RunPod Pod remained while the endpoint was offline for at least 60 minutes"
      metric_name         = "RunPodOrphanPodAgeMinutes"
      comparison_operator = "GreaterThanOrEqualToThreshold"
      threshold           = 60
      evaluation_periods  = 1
      datapoints_to_alarm = 1
      treat_missing_data  = "missing"
    }
    runtime_warning = {
      alarm_name          = "${local.name_prefix}-runpod-runtime-warning"
      description         = "A shared RunPod Pod exceeded the reviewed continuous runtime warning threshold"
      metric_name         = "RunPodRuntimeHours"
      comparison_operator = "GreaterThanOrEqualToThreshold"
      threshold           = var.runpod_runtime_warning_hours
      evaluation_periods  = 1
      datapoints_to_alarm = 1
      treat_missing_data  = "missing"
    }
  }
}

data "archive_file" "runpod_monitor" {
  type        = "zip"
  source_file = "${path.module}/../../delivery/lambda/runpod_monitor.py"
  output_path = "${path.module}/.terraform/runpod-monitor.zip"
}

resource "aws_cloudwatch_log_group" "runpod_monitor" {
  name              = "/aws/lambda/${local.name_prefix}-runpod-monitor"
  retention_in_days = 14

  tags = {
    Name = "/aws/lambda/${local.name_prefix}-runpod-monitor"
  }
}

resource "aws_iam_role" "runpod_monitor" {
  name               = "${local.name_prefix}-runpod-monitor"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

resource "aws_iam_role_policy" "runpod_monitor" {
  name = "${local.name_prefix}-runpod-monitor"
  role = aws_iam_role.runpod_monitor.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "WriteFunctionLogs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.runpod_monitor.arn}:*"
      },
      {
        Sid    = "ReadMonitorAndF2Keys"
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue"]
        Resource = [
          aws_secretsmanager_secret.runpod["monitor_api_key"].arn,
          aws_secretsmanager_secret.application["ai_provider"].arn,
        ]
      },
      {
        Sid      = "ReadEndpointControlDocument"
        Effect   = "Allow"
        Action   = ["ssm:GetParameter"]
        Resource = aws_ssm_parameter.ai_vllm_endpoint_set.arn
      },
      {
        Sid      = "WriteRunPodMetrics"
        Effect   = "Allow"
        Action   = ["cloudwatch:PutMetricData"]
        Resource = "*"
        Condition = {
          StringEquals = {
            "cloudwatch:namespace" = local.runtime_metric_namespace
          }
        }
      },
    ]
  })
}

resource "aws_lambda_function" "runpod_monitor" {
  function_name    = "${local.name_prefix}-runpod-monitor"
  role             = aws_iam_role.runpod_monitor.arn
  filename         = data.archive_file.runpod_monitor.output_path
  source_code_hash = data.archive_file.runpod_monitor.output_base64sha256
  handler          = "runpod_monitor.handler"
  runtime          = "python3.13"
  timeout          = 25

  environment {
    variables = {
      AI_PROVIDER_SECRET_ARN  = aws_secretsmanager_secret.application["ai_provider"].arn
      ENDPOINT_PARAMETER_NAME = aws_ssm_parameter.ai_vllm_endpoint_set.name
      METRIC_NAMESPACE        = local.runtime_metric_namespace
      MONITOR_SECRET_ARN      = aws_secretsmanager_secret.runpod["monitor_api_key"].arn
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.runpod_monitor,
    aws_iam_role_policy.runpod_monitor,
  ]
}

resource "aws_cloudwatch_event_rule" "runpod_monitor" {
  name                = "${local.name_prefix}-runpod-monitor"
  description         = "Read-only RunPod and authenticated F2 health observation"
  schedule_expression = "rate(${var.runpod_monitor_interval_minutes} minutes)"
}

resource "aws_cloudwatch_event_target" "runpod_monitor" {
  rule      = aws_cloudwatch_event_rule.runpod_monitor.name
  target_id = "RunPodMonitor"
  arn       = aws_lambda_function.runpod_monitor.arn
}

resource "aws_lambda_permission" "runpod_monitor_schedule" {
  statement_id  = "AllowEventBridgeRunPodMonitor"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.runpod_monitor.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.runpod_monitor.arn
}

resource "aws_cloudwatch_metric_alarm" "runpod_monitor_errors" {
  alarm_name          = "${local.name_prefix}-runpod-monitor-errors"
  alarm_description   = "The RunPod monitor Lambda returned an unhandled error"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  datapoints_to_alarm = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = local.runpod_monitor_period_seconds
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.runpod_monitor.function_name
  }

  alarm_actions = [aws_sns_topic.cloudwatch_alarms.arn]
  ok_actions    = [aws_sns_topic.cloudwatch_alarms.arn]

  depends_on = [
    aws_sns_topic_policy.cloudwatch_alarms,
    aws_sns_topic_subscription.cloudwatch_alarm_notifier,
  ]
}

resource "aws_cloudwatch_metric_alarm" "runpod_monitor_heartbeat" {
  alarm_name          = "${local.name_prefix}-runpod-monitor-heartbeat-missing"
  alarm_description   = "No successful RunPod monitor heartbeat arrived for two scheduled periods"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 2
  datapoints_to_alarm = 2
  metric_name         = "RunPodMonitorHeartbeat"
  namespace           = local.runtime_metric_namespace
  period              = local.runpod_monitor_period_seconds
  statistic           = "Minimum"
  threshold           = 1
  treat_missing_data  = "breaching"

  alarm_actions = [aws_sns_topic.cloudwatch_alarms.arn]
  ok_actions    = [aws_sns_topic.cloudwatch_alarms.arn]

  depends_on = [
    aws_sns_topic_policy.cloudwatch_alarms,
    aws_sns_topic_subscription.cloudwatch_alarm_notifier,
  ]
}

resource "aws_cloudwatch_metric_alarm" "runpod" {
  for_each = local.runpod_custom_alarms

  alarm_name          = each.value.alarm_name
  alarm_description   = each.value.description
  comparison_operator = each.value.comparison_operator
  evaluation_periods  = each.value.evaluation_periods
  datapoints_to_alarm = each.value.datapoints_to_alarm
  metric_name         = each.value.metric_name
  namespace           = local.runtime_metric_namespace
  period              = local.runpod_monitor_period_seconds
  statistic           = "Maximum"
  threshold           = each.value.threshold
  treat_missing_data  = each.value.treat_missing_data

  alarm_actions = [aws_sns_topic.cloudwatch_alarms.arn]
  ok_actions    = [aws_sns_topic.cloudwatch_alarms.arn]

  depends_on = [
    aws_sns_topic_policy.cloudwatch_alarms,
    aws_sns_topic_subscription.cloudwatch_alarm_notifier,
  ]
}

output "runpod_observability" {
  description = "Read-only RunPod monitor resources and adjustable thresholds"
  value = {
    function_name         = aws_lambda_function.runpod_monitor.function_name
    interval_minutes      = var.runpod_monitor_interval_minutes
    runtime_warning_hours = var.runpod_runtime_warning_hours
    alarm_names = concat(
      [
        aws_cloudwatch_metric_alarm.runpod_monitor_errors.alarm_name,
        aws_cloudwatch_metric_alarm.runpod_monitor_heartbeat.alarm_name,
      ],
      [for alarm in aws_cloudwatch_metric_alarm.runpod : alarm.alarm_name],
    )
  }
}
