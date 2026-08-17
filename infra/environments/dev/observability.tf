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

resource "aws_cloudwatch_metric_alarm" "alb_unhealthy_hosts" {
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
    LoadBalancer = aws_lb.app.arn_suffix
    TargetGroup  = aws_lb_target_group.app.arn_suffix
  }

  alarm_actions = [aws_sns_topic.runtime_alerts.arn]
  ok_actions    = [aws_sns_topic.runtime_alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "alb_target_5xx" {
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
    LoadBalancer = aws_lb.app.arn_suffix
    TargetGroup  = aws_lb_target_group.app.arn_suffix
  }

  alarm_actions = [aws_sns_topic.runtime_alerts.arn]
  ok_actions    = [aws_sns_topic.runtime_alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "asg_in_service_capacity" {
  alarm_name          = "${local.name_prefix}-asg-in-service-capacity"
  alarm_description   = "The application ASG has fewer than one in-service instance"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 2
  datapoints_to_alarm = 2
  metric_name         = "GroupInServiceInstances"
  namespace           = "AWS/AutoScaling"
  period              = 60
  statistic           = "Minimum"
  threshold           = 1
  treat_missing_data  = "breaching"

  dimensions = {
    AutoScalingGroupName = aws_autoscaling_group.app.name
  }

  alarm_actions = [aws_sns_topic.runtime_alerts.arn]
  ok_actions    = [aws_sns_topic.runtime_alerts.arn]
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

  alarm_actions = [aws_sns_topic.runtime_alerts.arn]
  ok_actions    = [aws_sns_topic.runtime_alerts.arn]
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

  alarm_actions = [aws_sns_topic.runtime_alerts.arn]
  ok_actions    = [aws_sns_topic.runtime_alerts.arn]
}

output "runtime_observability" {
  description = "운영 연결 단계가 참조할 runtime 관측 자원"
  value = {
    alarm_topic_arn = aws_sns_topic.runtime_alerts.arn
    log_group_names = { for purpose, group in aws_cloudwatch_log_group.runtime : purpose => group.name }
  }
}
