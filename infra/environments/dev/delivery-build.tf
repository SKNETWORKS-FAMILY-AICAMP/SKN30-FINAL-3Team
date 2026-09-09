data "aws_iam_policy_document" "codebuild_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["codebuild.amazonaws.com"]
    }
  }
}

resource "aws_cloudwatch_log_group" "delivery" {
  for_each = local.codebuild_projects

  name              = "/${local.name_prefix}/delivery/${replace(each.key, "_", "-")}"
  retention_in_days = 14

  tags = {
    Name = "/${local.name_prefix}/delivery/${replace(each.key, "_", "-")}"
  }
}

resource "aws_iam_role" "codebuild_admission" {
  name               = "${local.name_prefix}-codebuild-admission"
  assume_role_policy = data.aws_iam_policy_document.codebuild_assume_role.json
}

resource "aws_iam_role" "codebuild_backend" {
  name               = "${local.name_prefix}-codebuild-backend"
  assume_role_policy = data.aws_iam_policy_document.codebuild_assume_role.json
}

resource "aws_iam_role" "codebuild_backend_verify" {
  name               = "${local.name_prefix}-codebuild-backend-verify"
  assume_role_policy = data.aws_iam_policy_document.codebuild_assume_role.json
}

resource "aws_iam_role" "codebuild_frontend" {
  name               = "${local.name_prefix}-codebuild-frontend"
  assume_role_policy = data.aws_iam_policy_document.codebuild_assume_role.json
}

resource "aws_iam_role" "codebuild_frontend_verify" {
  name               = "${local.name_prefix}-codebuild-frontend-verify"
  assume_role_policy = data.aws_iam_policy_document.codebuild_assume_role.json
}

resource "aws_iam_role" "codebuild_frontend_deploy" {
  name               = "${local.name_prefix}-codebuild-frontend-deploy"
  assume_role_policy = data.aws_iam_policy_document.codebuild_assume_role.json
}

resource "aws_iam_role_policy" "codebuild_admission" {
  name = "${local.name_prefix}-codebuild-admission"
  role = aws_iam_role.codebuild_admission.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "PipelineStatus"
        Effect   = "Allow"
        Action   = ["codepipeline:ListPipelineExecutions"]
        Resource = [for name in local.delivery_pipeline_names : "arn:aws:codepipeline:${var.aws_region}:${data.aws_caller_identity.current.account_id}:${name}"]
      },
      {
        Sid      = "BuildLogs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = ["${aws_cloudwatch_log_group.delivery["admission"].arn}:*"]
      },
      {
        Sid      = "ArtifactRead"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:GetObjectVersion"]
        Resource = ["${aws_s3_bucket.workload["pipeline_artifact"].arn}/*"]
      },
    ]
  })
}

resource "aws_iam_role_policy" "codebuild_backend" {
  name = "${local.name_prefix}-codebuild-backend"
  role = aws_iam_role.codebuild_backend.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "Artifacts"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:GetObjectVersion", "s3:PutObject"]
        Resource = ["${aws_s3_bucket.workload["pipeline_artifact"].arn}/*"]
      },
      {
        Sid      = "EcrAuthorization"
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Sid    = "BackendRepository"
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:BatchGetImage",
          "ecr:CompleteLayerUpload",
          "ecr:DescribeImages",
          "ecr:GetDownloadUrlForLayer",
          "ecr:InitiateLayerUpload",
          "ecr:PutImage",
          "ecr:UploadLayerPart",
        ]
        Resource = aws_ecr_repository.backend_ai.arn
      },
      {
        Sid      = "BuildLogs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = ["${aws_cloudwatch_log_group.delivery["backend"].arn}:*"]
      },
    ]
  })
}

resource "aws_iam_role_policy" "codebuild_backend_verify" {
  name = "${local.name_prefix}-codebuild-backend-verify"
  role = aws_iam_role.codebuild_backend_verify.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ArtifactRead"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:GetObjectVersion"]
        Resource = ["${aws_s3_bucket.workload["pipeline_artifact"].arn}/*"]
      },
      {
        Sid      = "EcrAuthorization"
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Sid    = "CiPgvectorRepository"
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:BatchGetImage",
          "ecr:CompleteLayerUpload",
          "ecr:DescribeImages",
          "ecr:GetDownloadUrlForLayer",
          "ecr:InitiateLayerUpload",
          "ecr:PutImage",
          "ecr:UploadLayerPart",
        ]
        Resource = aws_ecr_repository.ci_pgvector.arn
      },
      {
        Sid      = "BuildLogs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = ["${aws_cloudwatch_log_group.delivery["backend_verify"].arn}:*"]
      },
    ]
  })
}

resource "aws_iam_role_policy" "codebuild_frontend" {
  name = "${local.name_prefix}-codebuild-frontend"
  role = aws_iam_role.codebuild_frontend.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "Artifacts"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:GetObjectVersion", "s3:PutObject"]
        Resource = ["${aws_s3_bucket.workload["pipeline_artifact"].arn}/*"]
      },
      {
        Sid      = "BuildLogs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = ["${aws_cloudwatch_log_group.delivery["frontend"].arn}:*"]
      },
    ]
  })
}

resource "aws_iam_role_policy" "codebuild_frontend_verify" {
  name = "${local.name_prefix}-codebuild-frontend-verify"
  role = aws_iam_role.codebuild_frontend_verify.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ArtifactRead"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:GetObjectVersion"]
        Resource = ["${aws_s3_bucket.workload["pipeline_artifact"].arn}/*"]
      },
      {
        Sid      = "BuildLogs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = ["${aws_cloudwatch_log_group.delivery["frontend_verify"].arn}:*"]
      },
    ]
  })
}

resource "aws_iam_role_policy" "codebuild_frontend_deploy" {
  name = "${local.name_prefix}-codebuild-frontend-deploy"
  role = aws_iam_role.codebuild_frontend_deploy.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadArtifacts"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:GetObjectVersion"]
        Resource = ["${aws_s3_bucket.workload["pipeline_artifact"].arn}/*"]
      },
      {
        Sid      = "BackupReleaseMetadata"
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:GetObject"]
        Resource = ["${aws_s3_bucket.workload["pipeline_artifact"].arn}/frontend-releases/*"]
      },
      {
        Sid    = "DeployFrontend"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:ListBucket",
          "s3:PutObject",
        ]
        Resource = [
          aws_s3_bucket.frontend.arn,
          "${aws_s3_bucket.frontend.arn}/*",
        ]
      },
      {
        Sid      = "InvalidateFrontend"
        Effect   = "Allow"
        Action   = ["cloudfront:CreateInvalidation", "cloudfront:GetInvalidation"]
        Resource = aws_cloudfront_distribution.frontend.arn
      },
      {
        Sid      = "BuildLogs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = ["${aws_cloudwatch_log_group.delivery["frontend_deploy"].arn}:*"]
      },
    ]
  })
}

resource "aws_codebuild_project" "admission" {
  name          = local.codebuild_projects.admission
  service_role  = aws_iam_role.codebuild_admission.arn
  build_timeout = 5

  artifacts {
    type = "CODEPIPELINE"
  }

  environment {
    compute_type = "BUILD_GENERAL1_SMALL"
    image        = "aws/codebuild/standard:7.0"
    type         = "LINUX_CONTAINER"

    environment_variable {
      name  = "APP_READINESS_PATH"
      value = local.application_ready_path
    }
  }

  source {
    type      = "CODEPIPELINE"
    buildspec = "infra/delivery/buildspec-admission.yml"
  }

  logs_config {
    cloudwatch_logs {
      group_name  = aws_cloudwatch_log_group.delivery["admission"].name
      stream_name = "admission"
    }
  }
}

resource "aws_codebuild_project" "backend" {
  name          = local.codebuild_projects.backend
  service_role  = aws_iam_role.codebuild_backend.arn
  build_timeout = 60

  artifacts {
    type = "CODEPIPELINE"
  }

  environment {
    compute_type    = "BUILD_GENERAL1_MEDIUM"
    image           = "aws/codebuild/standard:7.0"
    type            = "LINUX_CONTAINER"
    privileged_mode = true

    dynamic "environment_variable" {
      for_each = local.backend_build_environment

      content {
        name  = environment_variable.key
        value = environment_variable.value
      }
    }
  }

  source {
    type      = "CODEPIPELINE"
    buildspec = "infra/delivery/buildspec-backend-build.yml"
  }

  logs_config {
    cloudwatch_logs {
      group_name  = aws_cloudwatch_log_group.delivery["backend"].name
      stream_name = "backend"
    }
  }
}

resource "aws_codebuild_project" "backend_verify" {
  name          = local.codebuild_projects.backend_verify
  service_role  = aws_iam_role.codebuild_backend_verify.arn
  build_timeout = 60

  artifacts {
    type = "CODEPIPELINE"
  }

  environment {
    compute_type    = "BUILD_GENERAL1_MEDIUM"
    image           = "aws/codebuild/standard:7.0"
    type            = "LINUX_CONTAINER"
    privileged_mode = true

    environment_variable {
      name  = "AWS_REGION"
      value = var.aws_region
    }

    environment_variable {
      name  = "CI_PGVECTOR_REPOSITORY_NAME"
      value = aws_ecr_repository.ci_pgvector.name
    }

    environment_variable {
      name  = "CI_PGVECTOR_REPOSITORY_URI"
      value = aws_ecr_repository.ci_pgvector.repository_url
    }
  }

  source {
    type      = "CODEPIPELINE"
    buildspec = "infra/delivery/buildspec-backend-verify.yml"
  }

  logs_config {
    cloudwatch_logs {
      group_name  = aws_cloudwatch_log_group.delivery["backend_verify"].name
      stream_name = "backend-verify"
    }
  }
}

resource "aws_codebuild_project" "frontend" {
  name          = local.codebuild_projects.frontend
  service_role  = aws_iam_role.codebuild_frontend.arn
  build_timeout = 30

  artifacts {
    type = "CODEPIPELINE"
  }

  environment {
    compute_type = "BUILD_GENERAL1_SMALL"
    image        = "aws/codebuild/standard:7.0"
    type         = "LINUX_CONTAINER"

    dynamic "environment_variable" {
      for_each = local.frontend_build_environment

      content {
        name  = environment_variable.key
        value = environment_variable.value
      }
    }
  }

  source {
    type      = "CODEPIPELINE"
    buildspec = "infra/delivery/buildspec-frontend-build.yml"
  }

  logs_config {
    cloudwatch_logs {
      group_name  = aws_cloudwatch_log_group.delivery["frontend"].name
      stream_name = "frontend"
    }
  }
}

resource "aws_codebuild_project" "frontend_verify" {
  name          = local.codebuild_projects.frontend_verify
  service_role  = aws_iam_role.codebuild_frontend_verify.arn
  build_timeout = 30

  artifacts {
    type = "CODEPIPELINE"
  }

  environment {
    compute_type = "BUILD_GENERAL1_SMALL"
    image        = "aws/codebuild/standard:7.0"
    type         = "LINUX_CONTAINER"
  }

  source {
    type      = "CODEPIPELINE"
    buildspec = "infra/delivery/buildspec-frontend-verify.yml"
  }

  logs_config {
    cloudwatch_logs {
      group_name  = aws_cloudwatch_log_group.delivery["frontend_verify"].name
      stream_name = "frontend-verify"
    }
  }
}

resource "aws_codebuild_project" "frontend_deploy" {
  name          = local.codebuild_projects.frontend_deploy
  service_role  = aws_iam_role.codebuild_frontend_deploy.arn
  build_timeout = 20

  artifacts {
    type = "CODEPIPELINE"
  }

  environment {
    compute_type = "BUILD_GENERAL1_SMALL"
    image        = "aws/codebuild/standard:7.0"
    type         = "LINUX_CONTAINER"

    environment_variable {
      name  = "FRONTEND_BUCKET"
      value = aws_s3_bucket.frontend.id
    }

    environment_variable {
      name  = "ARTIFACT_BUCKET"
      value = aws_s3_bucket.workload["pipeline_artifact"].id
    }

    environment_variable {
      name  = "CLOUDFRONT_DISTRIBUTION_ID"
      value = aws_cloudfront_distribution.frontend.id
    }

    environment_variable {
      name  = "CLOUDFRONT_DOMAIN"
      value = aws_cloudfront_distribution.frontend.domain_name
    }

    environment_variable {
      name  = "APP_READINESS_PATH"
      value = local.application_ready_path
    }
  }

  source {
    type      = "CODEPIPELINE"
    buildspec = "buildspec.yml"
  }

  logs_config {
    cloudwatch_logs {
      group_name  = aws_cloudwatch_log_group.delivery["frontend_deploy"].name
      stream_name = "frontend-deploy"
    }
  }
}

