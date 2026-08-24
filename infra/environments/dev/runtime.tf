locals {
  runtime_metric_namespace = "${var.project_name}/${local.environment}"
  runtime_tags = {
    Project     = var.project_name
    Environment = local.environment
    ManagedBy   = "Terraform"
    Owner       = var.owner
    ExpiresAt   = var.expires_at
  }
}

data "aws_ssm_parameter" "al2023_x86_64_ami" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

data "aws_iam_policy_document" "app_instance_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "app_instance" {
  name               = "${local.name_prefix}-app-instance"
  assume_role_policy = data.aws_iam_policy_document.app_instance_assume_role.json

  tags = {
    Name = "${local.name_prefix}-app-instance"
  }
}

resource "aws_iam_role_policy_attachment" "app_ssm_core" {
  role       = aws_iam_role.app_instance.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

data "aws_iam_policy_document" "app_runtime" {
  statement {
    sid       = "EcrAuthorization"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid    = "PullBackendAiImages"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = [aws_ecr_repository.backend_ai.arn]
  }

  statement {
    sid    = "ReadDeploymentArtifacts"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:GetObjectVersion",
      "s3:ListBucket",
    ]
    resources = [
      aws_s3_bucket.workload["pipeline_artifact"].arn,
      "${aws_s3_bucket.workload["pipeline_artifact"].arn}/*",
    ]
  }

  statement {
    sid     = "ListWorkloadBuckets"
    effect  = "Allow"
    actions = ["s3:ListBucket"]
    resources = [
      aws_s3_bucket.workload["temporary_audio"].arn,
      aws_s3_bucket.workload["data_model"].arn,
    ]
  }

  statement {
    sid    = "ReadWriteBusinessObjects"
    effect = "Allow"
    actions = [
      "s3:AbortMultipartUpload",
      "s3:DeleteObject",
      "s3:GetObject",
      "s3:ListMultipartUploadParts",
      "s3:PutObject",
    ]
    resources = [
      "${aws_s3_bucket.workload["temporary_audio"].arn}/*",
      "${aws_s3_bucket.workload["data_model"].arn}/*",
    ]
  }

  statement {
    sid    = "ReadApplicationSecrets"
    effect = "Allow"
    actions = [
      "secretsmanager:DescribeSecret",
      "secretsmanager:GetSecretValue",
    ]
    resources = [
      aws_secretsmanager_secret.application["backend_runtime_database"].arn,
      aws_secretsmanager_secret.application["ai_provider"].arn,
    ]
  }

  statement {
    sid    = "ReadApplicationParameters"
    effect = "Allow"
    actions = [
      "ssm:GetParameter",
      "ssm:GetParameters",
      "ssm:GetParametersByPath",
    ]
    resources = concat(
      [for parameter in aws_ssm_parameter.application : parameter.arn],
      [
        "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/${local.name_prefix}",
        "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/${local.name_prefix}/*",
      ],
    )
  }

  statement {
    sid     = "ConnectAsMigrationRole"
    effect  = "Allow"
    actions = ["rds-db:connect"]
    resources = [
      "arn:aws:rds-db:${var.aws_region}:${data.aws_caller_identity.current.account_id}:dbuser:${aws_db_instance.postgres.resource_id}/app_migrator",
    ]
  }

  statement {
    sid       = "DescribeRuntimeLogGroups"
    effect    = "Allow"
    actions   = ["logs:DescribeLogGroups"]
    resources = ["*"]
  }

  statement {
    sid     = "DescribeRuntimeLogStreams"
    effect  = "Allow"
    actions = ["logs:DescribeLogStreams"]
    resources = [
      for purpose in ["api", "worker", "agent"] :
      aws_cloudwatch_log_group.runtime[purpose].arn
    ]
  }

  statement {
    sid    = "WriteRuntimeLogStreams"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      for purpose in ["api", "worker", "agent"] :
      "${aws_cloudwatch_log_group.runtime[purpose].arn}:*"
    ]
  }

  statement {
    sid       = "PublishRuntimeMetrics"
    effect    = "Allow"
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "cloudwatch:namespace"
      values   = [local.runtime_metric_namespace]
    }
  }

  statement {
    sid       = "ReadInstanceTagsForMetrics"
    effect    = "Allow"
    actions   = ["ec2:DescribeTags"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "app_runtime" {
  name   = "${local.name_prefix}-app-runtime"
  role   = aws_iam_role.app_instance.id
  policy = data.aws_iam_policy_document.app_runtime.json
}

resource "aws_iam_instance_profile" "app" {
  name = "${local.name_prefix}-app"
  role = aws_iam_role.app_instance.name
}

resource "aws_lb" "app" {
  name                       = "${local.name_prefix}-app"
  internal                   = false
  load_balancer_type         = "application"
  security_groups            = [aws_security_group.alb.id]
  subnets                    = [for subnet in aws_subnet.public : subnet.id]
  drop_invalid_header_fields = true
  enable_deletion_protection = false
  enable_http2               = true
  idle_timeout               = 60

  tags = {
    Name = "${local.name_prefix}-app"
  }
}

resource "aws_lb_target_group" "app" {
  name        = "${local.name_prefix}-app"
  port        = 8000
  protocol    = "HTTP"
  target_type = "instance"
  vpc_id      = aws_vpc.dev.id

  deregistration_delay = 30

  health_check {
    enabled             = true
    healthy_threshold   = 2
    interval            = 30
    matcher             = "200"
    path                = "/health/ready"
    port                = "traffic-port"
    protocol            = "HTTP"
    timeout             = 5
    unhealthy_threshold = 3
  }

  tags = {
    Name = "${local.name_prefix}-app"
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.app.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app.arn
  }
}

resource "aws_launch_template" "app" {
  name_prefix            = "${local.name_prefix}-app-"
  image_id               = data.aws_ssm_parameter.al2023_x86_64_ami.insecure_value
  instance_type          = "t3.small"
  update_default_version = true

  iam_instance_profile {
    arn = aws_iam_instance_profile.app.arn
  }

  network_interfaces {
    associate_public_ip_address = true
    delete_on_termination       = true
    device_index                = 0
    security_groups             = [aws_security_group.app.id]
  }

  block_device_mappings {
    device_name = "/dev/xvda"

    ebs {
      delete_on_termination = true
      encrypted             = true
      volume_size           = 40
      volume_type           = "gp3"
    }
  }

  credit_specification {
    cpu_credits = "standard"
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_protocol_ipv6          = "disabled"
    http_put_response_hop_limit = 1
    http_tokens                 = "required"
    instance_metadata_tags      = "disabled"
  }

  monitoring {
    enabled = false
  }

  user_data = base64encode(<<-EOT
    #!/bin/bash
    set -euo pipefail

    systemctl enable --now amazon-ssm-agent

    for attempt in 1 2 3; do
      if dnf install -y docker amazon-cloudwatch-agent ruby wget; then
        break
      fi
      if [ "$attempt" -eq 3 ]; then
        exit 1
      fi
      sleep 10
    done

    systemctl enable --now docker

    install -d -m 0755 /usr/local/lib/docker/cli-plugins
    curl -fsSL https://github.com/docker/compose/releases/download/v2.35.1/docker-compose-linux-x86_64 -o /usr/local/lib/docker/cli-plugins/docker-compose
    chmod 0755 /usr/local/lib/docker/cli-plugins/docker-compose
    docker compose version

    install -d -m 0755 /opt/brokerage/revision
    install -d -m 0700 /opt/brokerage/config

    cd /tmp
    wget -q https://aws-codedeploy-${var.aws_region}.s3.${var.aws_region}.amazonaws.com/latest/install -O codedeploy-install
    chmod 0700 codedeploy-install
    ./codedeploy-install auto
    systemctl enable --now codedeploy-agent
    systemctl is-active --quiet codedeploy-agent

    install -d -m 0755 /opt/aws/amazon-cloudwatch-agent/etc
    cat > /opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json <<'CWAGENT'
    {
      "agent": {
        "metrics_collection_interval": 60,
        "run_as_user": "root"
      },
      "metrics": {
        "namespace": "${local.runtime_metric_namespace}",
        "append_dimensions": {
          "AutoScalingGroupName": "$${aws:AutoScalingGroupName}",
          "InstanceId": "$${aws:InstanceId}"
        },
        "aggregation_dimensions": [["AutoScalingGroupName"]],
        "metrics_collected": {
          "disk": {
            "measurement": ["used_percent"],
            "metrics_collection_interval": 60,
            "resources": ["/"]
          },
          "mem": {
            "measurement": ["mem_used_percent"],
            "metrics_collection_interval": 60
          }
        }
      },
      "logs": {
        "logs_collected": {
          "files": {
            "collect_list": [
              {
                "file_path": "/opt/aws/amazon-cloudwatch-agent/logs/amazon-cloudwatch-agent.log",
                "log_group_name": "${aws_cloudwatch_log_group.runtime["agent"].name}",
                "log_stream_name": "{instance_id}"
              },
              {
                "file_path": "/var/log/cloud-init-output.log",
                "log_group_name": "${aws_cloudwatch_log_group.runtime["agent"].name}",
                "log_stream_name": "{instance_id}/cloud-init"
              }
            ]
          }
        }
      }
    }
    CWAGENT

    /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
      -a fetch-config \
      -m ec2 \
      -s \
      -c file:/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json
  EOT
  )

  tag_specifications {
    resource_type = "instance"
    tags = merge(local.runtime_tags, {
      Name = "${local.name_prefix}-app"
    })
  }

  tag_specifications {
    resource_type = "volume"
    tags = merge(local.runtime_tags, {
      Name = "${local.name_prefix}-app-root"
    })
  }

  tags = {
    Name = "${local.name_prefix}-app"
  }
}

resource "aws_autoscaling_group" "app" {
  name                = "${local.name_prefix}-app"
  min_size            = 0
  desired_capacity    = 1
  max_size            = 1
  vpc_zone_identifier = [for subnet in aws_subnet.public : subnet.id]
  target_group_arns   = [aws_lb_target_group.app.arn]

  health_check_type         = var.app_asg_health_check_type
  health_check_grace_period = 300
  capacity_rebalance        = false
  termination_policies      = ["OldestLaunchTemplate"]
  wait_for_capacity_timeout = "10m"

  enabled_metrics = [
    "GroupDesiredCapacity",
    "GroupInServiceInstances",
    "GroupTotalInstances",
  ]
  metrics_granularity = "1Minute"

  launch_template {
    id      = aws_launch_template.app.id
    version = aws_launch_template.app.latest_version
  }

  dynamic "tag" {
    for_each = merge(local.runtime_tags, { Name = "${local.name_prefix}-app-asg" })

    content {
      key                 = tag.key
      value               = tag.value
      propagate_at_launch = true
    }
  }

  depends_on = [
    aws_iam_role_policy_attachment.app_ssm_core,
    aws_iam_role_policy.app_runtime,
  ]

  lifecycle {
    # manage_dev_power.py owns the operational 0/1 state after creation.
    ignore_changes = [desired_capacity]
  }
}

output "application_load_balancer" {
  description = "CloudFront custom origin과 운영 검증에 사용할 ALB 식별자"
  value = {
    arn            = aws_lb.app.arn
    arn_suffix     = aws_lb.app.arn_suffix
    dns_name       = aws_lb.app.dns_name
    listener_arn   = aws_lb_listener.http.arn
    readiness_path = "/health/ready"
    readiness_prerequisites = [
      "Delivery must install and start the application artifact on port 8000.",
      "Delivery must materialize DB_URL and non-secret config; Backend API and worker startup must not require DB_MIGRATION_URL.",
      "A separate delivery identity must prepare database roles, schema, pgvector, and migrations.",
      "Backend must handle the dynamic ALB target-IP Host header without weakening the public origin boundary.",
    ]
    target_group_arn = aws_lb_target_group.app.arn
    zone_id          = aws_lb.app.zone_id
  }
}

output "app_runtime_identity" {
  description = "Delivery 단계가 참조할 애플리케이션 EC2 runtime 식별자"
  value = {
    asg_name                = aws_autoscaling_group.app.name
    instance_profile_arn    = aws_iam_instance_profile.app.arn
    instance_role_arn       = aws_iam_role.app_instance.arn
    launch_template_id      = aws_launch_template.app.id
    launch_template_version = aws_launch_template.app.latest_version
  }
}
