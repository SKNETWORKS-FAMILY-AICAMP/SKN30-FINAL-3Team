locals {
  s3_region_code = "apse2"

  workload_bucket_names = {
    temporary_audio   = "${var.project_name}-${local.environment}-audio-${local.s3_region_code}-${data.aws_caller_identity.current.account_id}"
    data_model        = "${var.project_name}-${local.environment}-data-model-${local.s3_region_code}-${data.aws_caller_identity.current.account_id}"
    pipeline_artifact = "${var.project_name}-${local.environment}-pipeline-${local.s3_region_code}-${data.aws_caller_identity.current.account_id}"
  }
}

resource "aws_s3_bucket" "workload" {
  for_each = local.workload_bucket_names

  bucket        = each.value
  force_destroy = false

  tags = {
    Name    = each.value
    Purpose = replace(each.key, "_", "-")
  }
}

resource "aws_s3_bucket_ownership_controls" "workload" {
  for_each = aws_s3_bucket.workload

  bucket = each.value.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "workload" {
  for_each = aws_s3_bucket.workload

  bucket = each.value.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "workload" {
  for_each = aws_s3_bucket.workload

  bucket = each.value.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "durable_workload" {
  for_each = toset(["data_model"])

  bucket = aws_s3_bucket.workload[each.key].id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "temporary_audio" {
  bucket = aws_s3_bucket.workload["temporary_audio"].id

  rule {
    id     = "expire-temporary-audio-safety-net"
    status = "Enabled"

    filter {}

    expiration {
      days = 1
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }

  depends_on = [aws_s3_bucket_server_side_encryption_configuration.workload]
}

resource "aws_s3_bucket_lifecycle_configuration" "data_model" {
  bucket = aws_s3_bucket.workload["data_model"].id

  rule {
    id     = "expire-releases-after-environment-end"
    status = "Enabled"

    filter {
      prefix = "releases/"
    }

    expiration {
      date = "2026-09-24T00:00:00Z"
    }

    noncurrent_version_expiration {
      noncurrent_days = 1
    }
  }

  rule {
    id     = "abort-incomplete-uploads"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  depends_on = [aws_s3_bucket_versioning.durable_workload]
}

resource "aws_s3_bucket_lifecycle_configuration" "pipeline_artifact" {
  bucket = aws_s3_bucket.workload["pipeline_artifact"].id

  rule {
    id     = "expire-pipeline-artifacts"
    status = "Enabled"

    filter {}

    expiration {
      days = 14
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

}

data "aws_iam_policy_document" "workload_bucket_tls_only" {
  for_each = local.workload_bucket_names

  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"

    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.workload[each.key].arn,
      "${aws_s3_bucket.workload[each.key].arn}/*",
    ]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "workload_tls_only" {
  for_each = aws_s3_bucket.workload

  bucket = each.value.id
  policy = data.aws_iam_policy_document.workload_bucket_tls_only[each.key].json

  depends_on = [aws_s3_bucket_public_access_block.workload]
}

resource "aws_ecr_repository" "backend_ai" {
  name                 = "${local.name_prefix}-backend-ai"
  image_tag_mutability = "IMMUTABLE"

  encryption_configuration {
    encryption_type = "AES256"
  }

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name = "${local.name_prefix}-backend-ai"
  }
}

resource "aws_ecr_lifecycle_policy" "backend_ai" {
  repository = aws_ecr_repository.backend_ai.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged images after seven days"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 7
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}

output "workload_bucket_names" {
  description = "런타임과 전달 구성이 참조할 목적별 S3 bucket 이름"
  value       = { for purpose, bucket in aws_s3_bucket.workload : purpose => bucket.id }
}

output "workload_bucket_arns" {
  description = "최소 권한 IAM 정책에서 참조할 목적별 S3 bucket ARN"
  value       = { for purpose, bucket in aws_s3_bucket.workload : purpose => bucket.arn }
}

output "backend_ai_ecr" {
  description = "Backend와 설치형 AI 이미지 저장소 식별자"
  value = {
    arn            = aws_ecr_repository.backend_ai.arn
    name           = aws_ecr_repository.backend_ai.name
    repository_url = aws_ecr_repository.backend_ai.repository_url
  }
}
