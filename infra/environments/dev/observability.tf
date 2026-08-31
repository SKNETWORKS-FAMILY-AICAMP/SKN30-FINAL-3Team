locals {
  runtime_log_group_names = {
    api            = "/${local.name_prefix}/application/api"
    worker         = "/${local.name_prefix}/application/worker"
    agent          = "/${local.name_prefix}/system/cloudwatch-agent"
    rds_postgresql = "/aws/rds/instance/${local.name_prefix}-postgres/postgresql"
    rds_upgrade    = "/aws/rds/instance/${local.name_prefix}-postgres/upgrade"
  }
}

resource "aws_cloudwatch_log_group" "runtime" {
  for_each = local.runtime_log_group_names

  name              = each.value
  retention_in_days = 14

  tags = {
    Name = each.value
  }
}

resource "aws_sns_topic" "runtime_alerts" {
  name = "${local.name_prefix}-runtime-alerts"

  tags = {
    Name = "${local.name_prefix}-runtime-alerts"
  }
}

resource "aws_sns_topic" "cloudwatch_alarms" {
  name = "${local.name_prefix}-cloudwatch-alarms"

  tags = {
    Name = "${local.name_prefix}-cloudwatch-alarms"
  }
}

data "aws_iam_policy_document" "cloudwatch_alarms_topic" {
  statement {
    sid    = "AccountAdministration"
    effect = "Allow"
    actions = [
      "sns:GetTopicAttributes",
      "sns:SetTopicAttributes",
      "sns:AddPermission",
      "sns:RemovePermission",
      "sns:DeleteTopic",
      "sns:Subscribe",
      "sns:ListSubscriptionsByTopic",
      "sns:Publish",
    ]
    resources = [aws_sns_topic.cloudwatch_alarms.arn]

    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
  }

  statement {
    sid       = "CloudWatchAlarmsPublish"
    effect    = "Allow"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.cloudwatch_alarms.arn]

    principals {
      type        = "Service"
      identifiers = ["cloudwatch.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:aws:cloudwatch:${var.aws_region}:${data.aws_caller_identity.current.account_id}:alarm:${local.name_prefix}-*"]
    }
  }
}

resource "aws_sns_topic_policy" "cloudwatch_alarms" {
  arn    = aws_sns_topic.cloudwatch_alarms.arn
  policy = data.aws_iam_policy_document.cloudwatch_alarms_topic.json
}

resource "aws_secretsmanager_secret" "alarm_discord_webhook" {
  name                    = "/${local.name_prefix}/observability/alarm-discord-webhook"
  description             = "CloudWatch alarm Discord webhook managed from the ignored secrets.auto.tfvars input"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "alarm_discord_webhook" {
  secret_id                = aws_secretsmanager_secret.alarm_discord_webhook.id
  secret_string_wo         = var.alarm_discord_webhook_url
  secret_string_wo_version = var.alarm_discord_webhook_secret_version
}

data "archive_file" "cloudwatch_alarm_notifier" {
  type        = "zip"
  source_file = "${path.module}/../../delivery/lambda/cloudwatch_alarm_notifier.py"
  output_path = "${path.module}/.terraform/cloudwatch-alarm-notifier.zip"
}

resource "aws_cloudwatch_log_group" "cloudwatch_alarm_notifier" {
  name              = "/aws/lambda/${local.name_prefix}-cloudwatch-alarm-notifier"
  retention_in_days = 14

  tags = {
    Name = "/aws/lambda/${local.name_prefix}-cloudwatch-alarm-notifier"
  }
}

resource "aws_iam_role" "cloudwatch_alarm_notifier" {
  name               = "${local.name_prefix}-cloudwatch-alarm-notifier"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

resource "aws_iam_role_policy" "cloudwatch_alarm_notifier" {
  name = "${local.name_prefix}-cloudwatch-alarm-notifier"
  role = aws_iam_role.cloudwatch_alarm_notifier.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "WriteFunctionLogs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.cloudwatch_alarm_notifier.arn}:*"
      },
      {
        Sid      = "ReadAlarmWebhook"
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = aws_secretsmanager_secret.alarm_discord_webhook.arn
      },
    ]
  })
}

resource "aws_lambda_function" "cloudwatch_alarm_notifier" {
  function_name    = "${local.name_prefix}-cloudwatch-alarm-notifier"
  role             = aws_iam_role.cloudwatch_alarm_notifier.arn
  filename         = data.archive_file.cloudwatch_alarm_notifier.output_path
  source_code_hash = data.archive_file.cloudwatch_alarm_notifier.output_base64sha256
  handler          = "cloudwatch_alarm_notifier.handler"
  runtime          = "python3.13"
  timeout          = 20

  environment {
    variables = {
      ALARM_DISCORD_SECRET_ARN = aws_secretsmanager_secret.alarm_discord_webhook.arn
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.cloudwatch_alarm_notifier,
    aws_iam_role_policy.cloudwatch_alarm_notifier,
    aws_secretsmanager_secret_version.alarm_discord_webhook,
  ]
}

resource "aws_lambda_permission" "cloudwatch_alarms" {
  statement_id  = "AllowCloudWatchAlarmsSns"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.cloudwatch_alarm_notifier.function_name
  principal     = "sns.amazonaws.com"
  source_arn    = aws_sns_topic.cloudwatch_alarms.arn
}

resource "aws_sns_topic_subscription" "cloudwatch_alarm_notifier" {
  topic_arn = aws_sns_topic.cloudwatch_alarms.arn
  protocol  = "lambda"
  endpoint  = aws_lambda_function.cloudwatch_alarm_notifier.arn

  depends_on = [aws_lambda_permission.cloudwatch_alarms]
}

resource "aws_cloudwatch_log_metric_filter" "backend_unhandled_error" {
  name           = "${local.name_prefix}-backend-unhandled-error"
  pattern        = "{ $.event = \"unhandled_request_error\" }"
  log_group_name = aws_cloudwatch_log_group.runtime["api"].name

  metric_transformation {
    name      = "BackendUnhandledErrorCount"
    namespace = local.runtime_metric_namespace
    value     = "1"
    unit      = "Count"
  }
}

resource "aws_cloudwatch_log_metric_filter" "ai_terminal_failure_api" {
  name           = "${local.name_prefix}-ai-terminal-failure-api"
  pattern        = "{ $.event = \"ai_terminal_failure\" }"
  log_group_name = aws_cloudwatch_log_group.runtime["api"].name

  metric_transformation {
    name      = "AiTerminalFailureCount"
    namespace = local.runtime_metric_namespace
    value     = "1"
    unit      = "Count"
  }
}

resource "aws_cloudwatch_log_metric_filter" "ai_terminal_failure_worker" {
  name           = "${local.name_prefix}-ai-terminal-failure-worker"
  pattern        = "{ $.event = \"ai_terminal_failure\" }"
  log_group_name = aws_cloudwatch_log_group.runtime["worker"].name

  metric_transformation {
    name      = "AiTerminalFailureCount"
    namespace = local.runtime_metric_namespace
    value     = "1"
    unit      = "Count"
  }
}

resource "aws_cloudwatch_metric_alarm" "backend_unhandled_errors" {
  alarm_name          = "${local.name_prefix}-backend-unhandled-errors"
  alarm_description   = "One or more unhandled Backend errors occurred in five minutes"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  datapoints_to_alarm = 1
  metric_name         = "BackendUnhandledErrorCount"
  namespace           = local.runtime_metric_namespace
  period              = 300
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.cloudwatch_alarms.arn]
  ok_actions    = [aws_sns_topic.cloudwatch_alarms.arn]

  depends_on = [
    aws_cloudwatch_log_metric_filter.backend_unhandled_error,
    aws_sns_topic_policy.cloudwatch_alarms,
    aws_sns_topic_subscription.cloudwatch_alarm_notifier,
  ]
}

resource "aws_cloudwatch_metric_alarm" "ai_terminal_failures" {
  alarm_name          = "${local.name_prefix}-ai-terminal-failures"
  alarm_description   = "One or more terminal AI failures occurred in five minutes"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  datapoints_to_alarm = 1
  metric_name         = "AiTerminalFailureCount"
  namespace           = local.runtime_metric_namespace
  period              = 300
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.cloudwatch_alarms.arn]
  ok_actions    = [aws_sns_topic.cloudwatch_alarms.arn]

  depends_on = [
    aws_cloudwatch_log_metric_filter.ai_terminal_failure_api,
    aws_cloudwatch_log_metric_filter.ai_terminal_failure_worker,
    aws_sns_topic_policy.cloudwatch_alarms,
    aws_sns_topic_subscription.cloudwatch_alarm_notifier,
  ]
}

resource "aws_cloudwatch_metric_alarm" "alb_unhealthy_hosts" {
  count = var.dev_edge_enabled ? 1 : 0

  alarm_name          = "${local.name_prefix}-alb-unhealthy-hosts"
  alarm_description   = "ALB target group has an unhealthy application host"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 2
  datapoints_to_alarm = 2
  metric_name         = "UnHealthyHostCount"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Maximum"
  threshold           = 1
  treat_missing_data  = "notBreaching"

  dimensions = {
    LoadBalancer = aws_lb.app[0].arn_suffix
    TargetGroup  = aws_lb_target_group.app.arn_suffix
  }

  alarm_actions = [aws_sns_topic.cloudwatch_alarms.arn]
  ok_actions    = [aws_sns_topic.cloudwatch_alarms.arn]

  depends_on = [
    aws_sns_topic_policy.cloudwatch_alarms,
    aws_sns_topic_subscription.cloudwatch_alarm_notifier,
  ]
}

resource "aws_cloudwatch_metric_alarm" "alb_target_5xx" {
  count = var.dev_edge_enabled ? 1 : 0

  alarm_name          = "${local.name_prefix}-alb-target-5xx"
  alarm_description   = "Application targets returned five or more 5xx responses in five minutes"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "HTTPCode_Target_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = 300
  statistic           = "Sum"
  threshold           = 5
  treat_missing_data  = "notBreaching"

  dimensions = {
    LoadBalancer = aws_lb.app[0].arn_suffix
    TargetGroup  = aws_lb_target_group.app.arn_suffix
  }

  alarm_actions = [aws_sns_topic.cloudwatch_alarms.arn]
  ok_actions    = [aws_sns_topic.cloudwatch_alarms.arn]

  depends_on = [
    aws_sns_topic_policy.cloudwatch_alarms,
    aws_sns_topic_subscription.cloudwatch_alarm_notifier,
  ]
}

moved {
  from = aws_cloudwatch_metric_alarm.alb_unhealthy_hosts
  to   = aws_cloudwatch_metric_alarm.alb_unhealthy_hosts[0]
}

moved {
  from = aws_cloudwatch_metric_alarm.alb_target_5xx
  to   = aws_cloudwatch_metric_alarm.alb_target_5xx[0]
}

resource "aws_cloudwatch_metric_alarm" "asg_in_service_capacity" {
  alarm_name          = "${local.name_prefix}-asg-in-service-capacity"
  alarm_description   = "The application ASG has fewer in-service instances than desired"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  datapoints_to_alarm = 2
  threshold           = 0
  treat_missing_data  = "breaching"

  metric_query {
    id          = "capacity_deficit"
    expression  = "desired - in_service"
    label       = "ASG desired capacity deficit"
    return_data = true
  }

  metric_query {
    id          = "desired"
    return_data = false

    metric {
      metric_name = "GroupDesiredCapacity"
      namespace   = "AWS/AutoScaling"
      period      = 60
      stat        = "Minimum"
      dimensions = {
        AutoScalingGroupName = aws_autoscaling_group.app.name
      }
    }
  }

  metric_query {
    id          = "in_service"
    return_data = false

    metric {
      metric_name = "GroupInServiceInstances"
      namespace   = "AWS/AutoScaling"
      period      = 60
      stat        = "Minimum"
      dimensions = {
        AutoScalingGroupName = aws_autoscaling_group.app.name
      }
    }
  }

  alarm_actions = [aws_sns_topic.cloudwatch_alarms.arn]
  ok_actions    = [aws_sns_topic.cloudwatch_alarms.arn]

  depends_on = [
    aws_sns_topic_policy.cloudwatch_alarms,
    aws_sns_topic_subscription.cloudwatch_alarm_notifier,
  ]
}

resource "aws_cloudwatch_metric_alarm" "rds_cpu_high" {
  alarm_name          = "${local.name_prefix}-rds-cpu-high"
  alarm_description   = "RDS CPU utilization remained at or above 80 percent"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 3
  datapoints_to_alarm = 3
  metric_name         = "CPUUtilization"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = 80
  treat_missing_data  = "missing"

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.postgres.identifier
  }

  alarm_actions = [aws_sns_topic.cloudwatch_alarms.arn]
  ok_actions    = [aws_sns_topic.cloudwatch_alarms.arn]

  depends_on = [
    aws_sns_topic_policy.cloudwatch_alarms,
    aws_sns_topic_subscription.cloudwatch_alarm_notifier,
  ]
}

resource "aws_cloudwatch_metric_alarm" "rds_free_storage_low" {
  alarm_name          = "${local.name_prefix}-rds-free-storage-low"
  alarm_description   = "RDS free storage is below five GiB"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 2
  datapoints_to_alarm = 2
  metric_name         = "FreeStorageSpace"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = 5368709120
  treat_missing_data  = "missing"

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.postgres.identifier
  }

  alarm_actions = [aws_sns_topic.cloudwatch_alarms.arn]
  ok_actions    = [aws_sns_topic.cloudwatch_alarms.arn]

  depends_on = [
    aws_sns_topic_policy.cloudwatch_alarms,
    aws_sns_topic_subscription.cloudwatch_alarm_notifier,
  ]
}

resource "aws_cloudwatch_metric_alarm" "rds_free_memory_low" {
  alarm_name          = "${local.name_prefix}-rds-free-memory-low"
  alarm_description   = "RDS free memory is below 256 MiB after enabling IAM database authentication"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 2
  datapoints_to_alarm = 2
  metric_name         = "FreeableMemory"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = 268435456
  treat_missing_data  = "missing"

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.postgres.identifier
  }

  alarm_actions = [aws_sns_topic.cloudwatch_alarms.arn]
  ok_actions    = [aws_sns_topic.cloudwatch_alarms.arn]

  depends_on = [
    aws_sns_topic_policy.cloudwatch_alarms,
    aws_sns_topic_subscription.cloudwatch_alarm_notifier,
  ]
}

output "runtime_observability" {
  description = "운영 연결 단계가 참조할 runtime 관측 자원"
  value = {
    alarm_topic_arn          = aws_sns_topic.cloudwatch_alarms.arn
    alarm_notifier_name      = aws_lambda_function.cloudwatch_alarm_notifier.function_name
    alarm_discord_secret_arn = aws_secretsmanager_secret.alarm_discord_webhook.arn
    delivery_topic_arn       = aws_sns_topic.runtime_alerts.arn
    log_group_names          = { for purpose, group in aws_cloudwatch_log_group.runtime : purpose => group.name }
  }
}
