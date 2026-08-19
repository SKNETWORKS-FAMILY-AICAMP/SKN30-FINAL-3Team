data "aws_partition" "current" {}

resource "aws_iam_group" "team_db_tunnel" {
  name = "team-db-tunnel"
  path = "/"
}

data "aws_iam_policy_document" "team_db_tunnel" {
  statement {
    sid     = "StartPortForwardingOnDevApp"
    effect  = "Allow"
    actions = ["ssm:StartSession"]
    resources = [
      "arn:${data.aws_partition.current.partition}:ec2:${var.aws_region}:${var.target_account_id}:instance/*",
    ]

    condition {
      test     = "StringEquals"
      variable = "ssm:resourceTag/Project"
      values   = [var.project_name]
    }

    condition {
      test     = "StringEquals"
      variable = "ssm:resourceTag/Environment"
      values   = [local.environment]
    }

    condition {
      test     = "StringEquals"
      variable = "ssm:resourceTag/ManagedBy"
      values   = ["Terraform"]
    }
  }

  statement {
    sid     = "UseRemoteHostPortForwardingDocument"
    effect  = "Allow"
    actions = ["ssm:StartSession"]
    resources = [
      "arn:${data.aws_partition.current.partition}:ssm:${var.aws_region}::document/AWS-StartPortForwardingSessionToRemoteHost",
    ]
  }

  statement {
    sid     = "OpenOwnSessionDataChannel"
    effect  = "Allow"
    actions = ["ssmmessages:OpenDataChannel"]
    resources = [
      "arn:${data.aws_partition.current.partition}:ssm:${var.aws_region}:${var.target_account_id}:session/$${aws:userid}-*",
    ]
  }

  statement {
    sid    = "ManageOwnSessions"
    effect = "Allow"
    actions = [
      "ssm:ResumeSession",
      "ssm:TerminateSession",
    ]
    resources = [
      "arn:${data.aws_partition.current.partition}:ssm:${var.aws_region}:${var.target_account_id}:session/$${aws:userid}-*",
    ]
  }

  statement {
    sid    = "DiscoverSessionTargets"
    effect = "Allow"
    actions = [
      "ec2:DescribeInstances",
      "rds:DescribeDBInstances",
      "ssm:DescribeInstanceInformation",
      "ssm:DescribeSessions",
      "ssm:GetConnectionStatus",
    ]
    resources = ["*"]
  }

  statement {
    sid     = "ConnectAsMatchingDatabaseUser"
    effect  = "Allow"
    actions = ["rds-db:connect"]
    resources = [
      "arn:${data.aws_partition.current.partition}:rds-db:${var.aws_region}:${var.target_account_id}:dbuser:${aws_db_instance.postgres.resource_id}/$${aws:username}",
    ]
  }
}

resource "aws_iam_policy" "team_db_tunnel" {
  name        = "${local.name_prefix}-team-db-tunnel"
  description = "Allow port-forwarding sessions through tagged dev application instances"
  policy      = data.aws_iam_policy_document.team_db_tunnel.json
}

resource "aws_iam_group_policy_attachment" "team_db_tunnel_aws_login" {
  group      = aws_iam_group.team_db_tunnel.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/SignInLocalDevelopmentAccess"
}

resource "aws_iam_group_policy_attachment" "team_db_tunnel_ssm" {
  group      = aws_iam_group.team_db_tunnel.name
  policy_arn = aws_iam_policy.team_db_tunnel.arn
}
