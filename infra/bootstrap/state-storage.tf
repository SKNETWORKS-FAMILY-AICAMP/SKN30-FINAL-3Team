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
