locals {
  state_bucket_name = "${var.project_name}-tfstate-${var.target_account_id}-${var.aws_region}"
  operator_user_names = {
    for arn in var.operator_user_arns : arn => element(reverse(split("/", arn)), 0)
  }
  state_keys = [
    "bootstrap/terraform.tfstate",
    "bootstrap/terraform.tfstate.tflock",
    "environments/dev/terraform.tfstate",
    "environments/dev/terraform.tfstate.tflock",
  ]
}

resource "aws_s3_account_public_access_block" "this" {
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_iam_account_password_policy" "this" {
  minimum_password_length        = 14
  require_lowercase_characters   = true
  require_numbers                = true
  require_symbols                = true
  require_uppercase_characters   = true
  allow_users_to_change_password = true
  hard_expiry                    = false
  max_password_age               = 90
  password_reuse_prevention      = 24
}

data "aws_iam_policy_document" "operator_trust" {
  statement {
    sid     = "AllowApprovedAwsLoginUsers"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "AWS"
      identifiers = var.operator_user_arns
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SignInSessionArn"
      values   = ["arn:${data.aws_partition.current.partition}:signin:*:${var.target_account_id}:session/*"]
    }

    condition {
      test     = "DateLessThan"
      variable = "aws:CurrentTime"
      values   = ["${var.expires_at}T23:59:59Z"]
    }
  }
}

resource "aws_iam_role" "terraform_operator" {
  name                 = "TerraformOperatorRole"
  description          = "Temporary Terraform deployment role; replace with Identity Center before production"
  assume_role_policy   = data.aws_iam_policy_document.operator_trust.json
  max_session_duration = 3600
}

resource "aws_iam_role_policy_attachment" "terraform_operator_admin" {
  role       = aws_iam_role.terraform_operator.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/AdministratorAccess"
}

data "aws_iam_policy_document" "assume_operator" {
  statement {
    sid       = "AssumeTerraformOperatorWithMFA"
    effect    = "Allow"
    actions   = ["sts:AssumeRole"]
    resources = [aws_iam_role.terraform_operator.arn]
  }
}

resource "aws_iam_user_policy" "assume_operator" {
  for_each = local.operator_user_names

  name   = "AssumeTerraformOperatorRole"
  user   = each.value
  policy = data.aws_iam_policy_document.assume_operator.json
}

resource "aws_iam_user_policy_attachment" "aws_login" {
  for_each = local.operator_user_names

  user       = each.value
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/SignInLocalDevelopmentAccess"
}

resource "aws_s3_bucket" "terraform_state" {
  bucket = local.state_bucket_name

  lifecycle {
    prevent_destroy = true

    precondition {
      condition     = length(local.state_bucket_name) <= 63
      error_message = "계산된 state bucket 이름이 S3의 63자 제한을 초과합니다."
    }
  }
}

resource "aws_s3_bucket_ownership_controls" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  rule {
    id     = "retain-noncurrent-state-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 90
    }
  }

  depends_on = [aws_s3_bucket_versioning.terraform_state]
}

data "aws_iam_policy_document" "terraform_state" {
  statement {
    sid    = "RequireTLS"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.terraform_state.arn,
      "${aws_s3_bucket.terraform_state.arn}/*",
    ]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  statement {
    sid    = "RestrictStateListingToOperator"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.terraform_state.arn]

    condition {
      test     = "ArnNotEquals"
      variable = "aws:PrincipalArn"
      values = [
        aws_iam_role.terraform_operator.arn,
        "arn:${data.aws_partition.current.partition}:iam::${var.target_account_id}:root",
      ]
    }
  }

  statement {
    sid    = "RestrictStateObjectsToOperator"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions = [
      "s3:DeleteObject",
      "s3:GetObject",
      "s3:PutObject",
    ]
    resources = [for key in local.state_keys : "${aws_s3_bucket.terraform_state.arn}/${key}"]

    condition {
      test     = "ArnNotEquals"
      variable = "aws:PrincipalArn"
      values = [
        aws_iam_role.terraform_operator.arn,
        "arn:${data.aws_partition.current.partition}:iam::${var.target_account_id}:root",
      ]
    }
  }

  statement {
    sid    = "AllowOperatorBucketLocation"
    effect = "Allow"

    principals {
      type        = "AWS"
      identifiers = [aws_iam_role.terraform_operator.arn]
    }

    actions   = ["s3:GetBucketLocation"]
    resources = [aws_s3_bucket.terraform_state.arn]
  }

  statement {
    sid    = "AllowOperatorToListState"
    effect = "Allow"

    principals {
      type        = "AWS"
      identifiers = [aws_iam_role.terraform_operator.arn]
    }

    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.terraform_state.arn]

    condition {
      test     = "StringEquals"
      variable = "s3:prefix"
      values   = local.state_keys
    }
  }

  statement {
    sid    = "AllowOperatorStateObjects"
    effect = "Allow"

    principals {
      type        = "AWS"
      identifiers = [aws_iam_role.terraform_operator.arn]
    }

    actions = [
      "s3:GetObject",
      "s3:PutObject",
    ]
    resources = [
      "${aws_s3_bucket.terraform_state.arn}/bootstrap/terraform.tfstate",
      "${aws_s3_bucket.terraform_state.arn}/environments/dev/terraform.tfstate",
    ]
  }

  statement {
    sid    = "AllowOperatorLockObjects"
    effect = "Allow"

    principals {
      type        = "AWS"
      identifiers = [aws_iam_role.terraform_operator.arn]
    }

    actions = [
      "s3:DeleteObject",
      "s3:GetObject",
      "s3:PutObject",
    ]
    resources = [
      "${aws_s3_bucket.terraform_state.arn}/bootstrap/terraform.tfstate.tflock",
      "${aws_s3_bucket.terraform_state.arn}/environments/dev/terraform.tfstate.tflock",
    ]
  }
}

resource "aws_s3_bucket_policy" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id
  policy = data.aws_iam_policy_document.terraform_state.json

  depends_on = [aws_s3_bucket_public_access_block.terraform_state]
}

resource "aws_budgets_budget" "monthly" {
  count = var.create_budget ? 1 : 0

  name         = "${var.project_name}-monthly-cost"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_amount)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  dynamic "notification" {
    for_each = toset([50, 80, 100])

    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = [var.budget_notification_email]
    }
  }
}
