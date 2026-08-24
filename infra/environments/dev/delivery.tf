locals {
  delivery_pipeline_names = {
    integrated = "${local.name_prefix}-integrated"
    backend    = "${local.name_prefix}-backend"
    frontend   = "${local.name_prefix}-frontend"
  }

  codebuild_projects = {
    admission       = "${local.name_prefix}-admission"
    backend_verify  = "${local.name_prefix}-backend-verify"
    backend         = "${local.name_prefix}-backend-build"
    frontend_verify = "${local.name_prefix}-frontend-verify"
    frontend        = "${local.name_prefix}-frontend-build"
    frontend_deploy = "${local.name_prefix}-frontend-deploy"
  }
}

resource "aws_codeconnections_connection" "github" {
  name          = "SKN30_FINAL"
  provider_type = "GitHub"

  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Name = "SKN30_FINAL"
  }
}

import {
  to = aws_codeconnections_connection.github
  id = var.github_connection_arn
}

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

    environment_variable {
      name  = "AWS_REGION"
      value = var.aws_region
    }

    environment_variable {
      name  = "ECR_REPOSITORY_NAME"
      value = aws_ecr_repository.backend_ai.name
    }

    environment_variable {
      name  = "ECR_REPOSITORY_URI"
      value = aws_ecr_repository.backend_ai.repository_url
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

data "aws_iam_policy_document" "codedeploy_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["codedeploy.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "codedeploy" {
  name               = "${local.name_prefix}-codedeploy"
  assume_role_policy = data.aws_iam_policy_document.codedeploy_assume_role.json
}

resource "aws_iam_role_policy_attachment" "codedeploy" {
  role       = aws_iam_role.codedeploy.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSCodeDeployRole"
}

resource "aws_codedeploy_app" "backend" {
  compute_platform = "Server"
  name             = "${local.name_prefix}-backend"
}

resource "aws_codedeploy_deployment_group" "backend" {
  app_name               = aws_codedeploy_app.backend.name
  deployment_group_name  = "${local.name_prefix}-backend"
  deployment_config_name = "CodeDeployDefault.AllAtOnce"
  service_role_arn       = aws_iam_role.codedeploy.arn
  autoscaling_groups     = [aws_autoscaling_group.app.name]

  auto_rollback_configuration {
    enabled = true
    events  = ["DEPLOYMENT_FAILURE"]
  }

  deployment_style {
    deployment_option = "WITH_TRAFFIC_CONTROL"
    deployment_type   = "IN_PLACE"
  }

  load_balancer_info {
    target_group_info {
      name = aws_lb_target_group.app.name
    }
  }
}

data "aws_iam_policy_document" "codepipeline_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["codepipeline.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "codepipeline" {
  for_each = local.delivery_pipeline_names

  name               = "${each.value}-pipeline"
  assume_role_policy = data.aws_iam_policy_document.codepipeline_assume_role.json
}

resource "aws_iam_role_policy" "codepipeline" {
  for_each = local.delivery_pipeline_names

  name = "${each.value}-pipeline"
  role = aws_iam_role.codepipeline[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "UseConnection"
        Effect   = "Allow"
        Action   = ["codeconnections:UseConnection"]
        Resource = aws_codeconnections_connection.github.arn
      },
      {
        Sid    = "Artifacts"
        Effect = "Allow"
        Action = [
          "s3:GetBucketVersioning",
          "s3:GetObject",
          "s3:GetObjectVersion",
          "s3:PutObject",
        ]
        Resource = [
          aws_s3_bucket.workload["pipeline_artifact"].arn,
          "${aws_s3_bucket.workload["pipeline_artifact"].arn}/*",
        ]
      },
      {
        Sid    = "RunBuilds"
        Effect = "Allow"
        Action = ["codebuild:StartBuild", "codebuild:BatchGetBuilds"]
        Resource = each.key == "integrated" ? [
          aws_codebuild_project.admission.arn,
          aws_codebuild_project.backend_verify.arn,
          aws_codebuild_project.backend.arn,
          aws_codebuild_project.frontend_verify.arn,
          aws_codebuild_project.frontend.arn,
          aws_codebuild_project.frontend_deploy.arn,
          ] : each.key == "backend" ? [
          aws_codebuild_project.admission.arn,
          aws_codebuild_project.backend_verify.arn,
          aws_codebuild_project.backend.arn,
          ] : [
          aws_codebuild_project.admission.arn,
          aws_codebuild_project.frontend_verify.arn,
          aws_codebuild_project.frontend.arn,
          aws_codebuild_project.frontend_deploy.arn,
        ]
      },
    ]
  })
}

resource "aws_iam_role_policy" "codepipeline_backend_deploy" {
  for_each = { for key, name in local.delivery_pipeline_names : key => name if key != "frontend" }

  name = "${each.value}-backend-deploy"
  role = aws_iam_role.codepipeline[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "DeployBackend"
        Effect = "Allow"
        Action = [
          "codedeploy:CreateDeployment",
          "codedeploy:GetApplication",
          "codedeploy:GetApplicationRevision",
          "codedeploy:GetDeployment",
          "codedeploy:GetDeploymentConfig",
          "codedeploy:RegisterApplicationRevision",
        ]
        Resource = "*"
      },
    ]
  })
}

resource "aws_codepipeline" "integrated" {
  name           = local.delivery_pipeline_names.integrated
  role_arn       = aws_iam_role.codepipeline["integrated"].arn
  pipeline_type  = "V2"
  execution_mode = "QUEUED"

  artifact_store {
    location = aws_s3_bucket.workload["pipeline_artifact"].id
    type     = "S3"
  }

  stage {
    name = "Source"

    action {
      name             = "Source"
      category         = "Source"
      owner            = "AWS"
      provider         = "CodeStarSourceConnection"
      version          = "1"
      output_artifacts = ["SourceArtifact"]

      configuration = {
        BranchName           = "dev"
        ConnectionArn        = aws_codeconnections_connection.github.arn
        DetectChanges        = false
        FullRepositoryId     = var.github_full_repository_id
        OutputArtifactFormat = "CODE_ZIP"
      }
    }
  }

  stage {
    name = "Admission"

    action {
      name            = "CheckOtherPipelines"
      category        = "Build"
      owner           = "AWS"
      provider        = "CodeBuild"
      version         = "1"
      input_artifacts = ["SourceArtifact"]

      configuration = {
        ProjectName = aws_codebuild_project.admission.name
        EnvironmentVariables = jsonencode([
          { name = "CURRENT_PIPELINE", value = local.delivery_pipeline_names.integrated, type = "PLAINTEXT" },
          { name = "OTHER_PIPELINES", value = "${local.delivery_pipeline_names.backend} ${local.delivery_pipeline_names.frontend}", type = "PLAINTEXT" },
          { name = "PIPELINE_KIND", value = "integrated", type = "PLAINTEXT" },
          { name = "PIPELINE_EXECUTION_ID", value = "#{codepipeline.PipelineExecutionId}", type = "PLAINTEXT" },
        ])
      }
    }
  }

  stage {
    name = "Verify"

    action {
      name            = "Backend"
      category        = "Build"
      owner           = "AWS"
      provider        = "CodeBuild"
      version         = "1"
      input_artifacts = ["SourceArtifact"]

      configuration = {
        ProjectName = aws_codebuild_project.backend_verify.name
      }
    }

    action {
      name            = "Frontend"
      category        = "Build"
      owner           = "AWS"
      provider        = "CodeBuild"
      version         = "1"
      input_artifacts = ["SourceArtifact"]

      configuration = {
        ProjectName = aws_codebuild_project.frontend_verify.name
      }
    }
  }

  stage {
    name = "Build"

    action {
      name             = "Backend"
      category         = "Build"
      owner            = "AWS"
      provider         = "CodeBuild"
      version          = "1"
      input_artifacts  = ["SourceArtifact"]
      output_artifacts = ["BackendRelease"]

      configuration = {
        ProjectName = aws_codebuild_project.backend.name
        EnvironmentVariables = jsonencode([
          { name = "PIPELINE_KIND", value = "integrated", type = "PLAINTEXT" },
          { name = "PIPELINE_EXECUTION_ID", value = "#{codepipeline.PipelineExecutionId}", type = "PLAINTEXT" },
        ])
      }
    }

    action {
      name             = "Frontend"
      category         = "Build"
      owner            = "AWS"
      provider         = "CodeBuild"
      version          = "1"
      input_artifacts  = ["SourceArtifact"]
      output_artifacts = ["FrontendRelease"]

      configuration = {
        ProjectName = aws_codebuild_project.frontend.name
        EnvironmentVariables = jsonencode([
          { name = "PIPELINE_KIND", value = "integrated", type = "PLAINTEXT" },
          { name = "PIPELINE_EXECUTION_ID", value = "#{codepipeline.PipelineExecutionId}", type = "PLAINTEXT" },
        ])
      }
    }
  }

  stage {
    name = "BackendDeploy"

    action {
      name            = "CodeDeploy"
      category        = "Deploy"
      owner           = "AWS"
      provider        = "CodeDeploy"
      version         = "1"
      input_artifacts = ["BackendRelease"]

      configuration = {
        ApplicationName     = aws_codedeploy_app.backend.name
        DeploymentGroupName = aws_codedeploy_deployment_group.backend.deployment_group_name
      }
    }
  }

  stage {
    name = "FrontendDeploy"

    action {
      name            = "DeployIndexLast"
      category        = "Build"
      owner           = "AWS"
      provider        = "CodeBuild"
      version         = "1"
      input_artifacts = ["FrontendRelease"]

      configuration = {
        ProjectName = aws_codebuild_project.frontend_deploy.name
        EnvironmentVariables = jsonencode([
          { name = "PIPELINE_EXECUTION_ID", value = "#{codepipeline.PipelineExecutionId}", type = "PLAINTEXT" },
        ])
      }
    }
  }
}

resource "aws_codepipeline" "backend" {
  name           = local.delivery_pipeline_names.backend
  role_arn       = aws_iam_role.codepipeline["backend"].arn
  pipeline_type  = "V2"
  execution_mode = "QUEUED"

  artifact_store {
    location = aws_s3_bucket.workload["pipeline_artifact"].id
    type     = "S3"
  }

  stage {
    name = "Source"

    action {
      name             = "Source"
      category         = "Source"
      owner            = "AWS"
      provider         = "CodeStarSourceConnection"
      version          = "1"
      output_artifacts = ["SourceArtifact"]

      configuration = {
        BranchName           = "dev"
        ConnectionArn        = aws_codeconnections_connection.github.arn
        DetectChanges        = "false"
        FullRepositoryId     = var.github_full_repository_id
        OutputArtifactFormat = "CODE_ZIP"
      }
    }
  }

  stage {
    name = "Admission"

    action {
      name            = "CheckOtherPipelines"
      category        = "Build"
      owner           = "AWS"
      provider        = "CodeBuild"
      version         = "1"
      input_artifacts = ["SourceArtifact"]

      configuration = {
        ProjectName = aws_codebuild_project.admission.name
        EnvironmentVariables = jsonencode([
          { name = "CURRENT_PIPELINE", value = local.delivery_pipeline_names.backend, type = "PLAINTEXT" },
          { name = "OTHER_PIPELINES", value = "${local.delivery_pipeline_names.integrated} ${local.delivery_pipeline_names.frontend}", type = "PLAINTEXT" },
          { name = "PIPELINE_KIND", value = "backend", type = "PLAINTEXT" },
          { name = "PIPELINE_EXECUTION_ID", value = "#{codepipeline.PipelineExecutionId}", type = "PLAINTEXT" },
        ])
      }
    }
  }

  stage {
    name = "Verify"

    action {
      name            = "Backend"
      category        = "Build"
      owner           = "AWS"
      provider        = "CodeBuild"
      version         = "1"
      input_artifacts = ["SourceArtifact"]

      configuration = {
        ProjectName = aws_codebuild_project.backend_verify.name
      }
    }
  }

  stage {
    name = "Build"

    action {
      name             = "Backend"
      category         = "Build"
      owner            = "AWS"
      provider         = "CodeBuild"
      version          = "1"
      input_artifacts  = ["SourceArtifact"]
      output_artifacts = ["BackendRelease"]

      configuration = {
        ProjectName = aws_codebuild_project.backend.name
        EnvironmentVariables = jsonencode([
          { name = "PIPELINE_KIND", value = "backend", type = "PLAINTEXT" },
          { name = "PIPELINE_EXECUTION_ID", value = "#{codepipeline.PipelineExecutionId}", type = "PLAINTEXT" },
        ])
      }
    }
  }

  stage {
    name = "Deploy"

    action {
      name            = "CodeDeploy"
      category        = "Deploy"
      owner           = "AWS"
      provider        = "CodeDeploy"
      version         = "1"
      input_artifacts = ["BackendRelease"]

      configuration = {
        ApplicationName     = aws_codedeploy_app.backend.name
        DeploymentGroupName = aws_codedeploy_deployment_group.backend.deployment_group_name
      }
    }
  }
}

resource "aws_codepipeline" "frontend" {
  name           = local.delivery_pipeline_names.frontend
  role_arn       = aws_iam_role.codepipeline["frontend"].arn
  pipeline_type  = "V2"
  execution_mode = "QUEUED"

  artifact_store {
    location = aws_s3_bucket.workload["pipeline_artifact"].id
    type     = "S3"
  }

  stage {
    name = "Source"

    action {
      name             = "Source"
      category         = "Source"
      owner            = "AWS"
      provider         = "CodeStarSourceConnection"
      version          = "1"
      output_artifacts = ["SourceArtifact"]

      configuration = {
        BranchName           = "dev"
        ConnectionArn        = aws_codeconnections_connection.github.arn
        DetectChanges        = "false"
        FullRepositoryId     = var.github_full_repository_id
        OutputArtifactFormat = "CODE_ZIP"
      }
    }
  }

  stage {
    name = "Admission"

    action {
      name            = "CheckOtherPipelines"
      category        = "Build"
      owner           = "AWS"
      provider        = "CodeBuild"
      version         = "1"
      input_artifacts = ["SourceArtifact"]

      configuration = {
        ProjectName = aws_codebuild_project.admission.name
        EnvironmentVariables = jsonencode([
          { name = "CURRENT_PIPELINE", value = local.delivery_pipeline_names.frontend, type = "PLAINTEXT" },
          { name = "OTHER_PIPELINES", value = "${local.delivery_pipeline_names.integrated} ${local.delivery_pipeline_names.backend}", type = "PLAINTEXT" },
          { name = "PIPELINE_KIND", value = "frontend", type = "PLAINTEXT" },
          { name = "PIPELINE_EXECUTION_ID", value = "#{codepipeline.PipelineExecutionId}", type = "PLAINTEXT" },
          { name = "BACKEND_ORIGIN", value = "https://${aws_cloudfront_distribution.frontend.domain_name}", type = "PLAINTEXT" },
        ])
      }
    }
  }

  stage {
    name = "Verify"

    action {
      name            = "Frontend"
      category        = "Build"
      owner           = "AWS"
      provider        = "CodeBuild"
      version         = "1"
      input_artifacts = ["SourceArtifact"]

      configuration = {
        ProjectName = aws_codebuild_project.frontend_verify.name
      }
    }
  }

  stage {
    name = "Build"

    action {
      name             = "Frontend"
      category         = "Build"
      owner            = "AWS"
      provider         = "CodeBuild"
      version          = "1"
      input_artifacts  = ["SourceArtifact"]
      output_artifacts = ["FrontendRelease"]

      configuration = {
        ProjectName = aws_codebuild_project.frontend.name
        EnvironmentVariables = jsonencode([
          { name = "PIPELINE_KIND", value = "frontend", type = "PLAINTEXT" },
          { name = "PIPELINE_EXECUTION_ID", value = "#{codepipeline.PipelineExecutionId}", type = "PLAINTEXT" },
        ])
      }
    }
  }

  stage {
    name = "Deploy"

    action {
      name            = "DeployIndexLast"
      category        = "Build"
      owner           = "AWS"
      provider        = "CodeBuild"
      version         = "1"
      input_artifacts = ["FrontendRelease"]

      configuration = {
        ProjectName = aws_codebuild_project.frontend_deploy.name
        EnvironmentVariables = jsonencode([
          { name = "PIPELINE_EXECUTION_ID", value = "#{codepipeline.PipelineExecutionId}", type = "PLAINTEXT" },
        ])
      }
    }
  }
}

resource "aws_iam_policy" "pipeline_operator" {
  name        = "${local.name_prefix}-pipeline-operator"
  description = "Least-privilege manual operation policy for approved existing IAM users"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "DiscoverDeliveryPipelines"
        Effect   = "Allow"
        Action   = ["codepipeline:ListPipelines"]
        Resource = "*"
      },
      {
        Sid    = "OperateDeliveryPipelines"
        Effect = "Allow"
        Action = [
          "codepipeline:GetPipeline",
          "codepipeline:GetPipelineExecution",
          "codepipeline:GetPipelineState",
          "codepipeline:ListActionExecutions",
          "codepipeline:ListPipelineExecutions",
          "codepipeline:StartPipelineExecution",
          "codepipeline:StopPipelineExecution",
        ]
        Resource = [for name in local.delivery_pipeline_names : "arn:aws:codepipeline:${var.aws_region}:${data.aws_caller_identity.current.account_id}:${name}"]
      },
    ]
  })
}

resource "aws_iam_user_policy_attachment" "pipeline_operator" {
  for_each = var.pipeline_operator_user_names

  user       = each.value
  policy_arn = aws_iam_policy.pipeline_operator.arn
}

resource "aws_secretsmanager_secret" "discord_webhook" {
  name                    = "/${local.name_prefix}/delivery/discord-webhook"
  description             = "Container for a Discord webhook URL; value is populated outside Terraform"
  recovery_window_in_days = 7
}

data "archive_file" "discord_notifier" {
  type        = "zip"
  source_file = "${path.module}/../../delivery/lambda/discord_notifier.py"
  output_path = "${path.module}/.terraform/discord-notifier.zip"
}

data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "discord_notifier" {
  name               = "${local.name_prefix}-discord-notifier"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

resource "aws_iam_role_policy" "discord_notifier" {
  name = "${local.name_prefix}-discord-notifier"
  role = aws_iam_role.discord_notifier.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "Logs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${local.name_prefix}-discord-notifier:*"
      },
      {
        Sid      = "ReadWebhook"
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = aws_secretsmanager_secret.discord_webhook.arn
      },
      {
        Sid      = "ReadDeliveryState"
        Effect   = "Allow"
        Action   = ["codepipeline:GetPipelineExecution", "codepipeline:ListActionExecutions"]
        Resource = [for name in local.delivery_pipeline_names : "arn:aws:codepipeline:${var.aws_region}:${data.aws_caller_identity.current.account_id}:${name}"]
      },
      {
        Sid      = "ReadDeploymentState"
        Effect   = "Allow"
        Action   = ["codedeploy:GetDeployment"]
        Resource = "*"
      },
    ]
  })
}

resource "aws_lambda_function" "discord_notifier" {
  function_name    = "${local.name_prefix}-discord-notifier"
  role             = aws_iam_role.discord_notifier.arn
  filename         = data.archive_file.discord_notifier.output_path
  source_code_hash = data.archive_file.discord_notifier.output_base64sha256
  handler          = "discord_notifier.handler"
  runtime          = "python3.13"
  timeout          = 20

  environment {
    variables = {
      DISCORD_SECRET_ARN = aws_secretsmanager_secret.discord_webhook.arn
    }
  }
}

resource "aws_sns_topic_subscription" "discord_notifier" {
  topic_arn = aws_sns_topic.runtime_alerts.arn
  protocol  = "lambda"
  endpoint  = aws_lambda_function.discord_notifier.arn
}

resource "aws_lambda_permission" "runtime_alerts" {
  statement_id  = "AllowRuntimeAlertsSns"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.discord_notifier.function_name
  principal     = "sns.amazonaws.com"
  source_arn    = aws_sns_topic.runtime_alerts.arn
}

resource "aws_cloudwatch_event_rule" "pipeline_state" {
  name        = "${local.name_prefix}-pipeline-state"
  description = "Delivery pipeline completion events"

  event_pattern = jsonencode({
    source      = ["aws.codepipeline"]
    detail-type = ["CodePipeline Pipeline Execution State Change"]
    detail = {
      pipeline = values(local.delivery_pipeline_names)
      state    = ["SUCCEEDED", "FAILED", "CANCELED", "SUPERSEDED"]
    }
  })
}

resource "aws_cloudwatch_event_rule" "codedeploy_state" {
  name        = "${local.name_prefix}-codedeploy-state"
  description = "Backend deployment and rollback events"

  event_pattern = jsonencode({
    source      = ["aws.codedeploy"]
    detail-type = ["CodeDeploy Deployment State-change Notification"]
    detail = {
      application = [aws_codedeploy_app.backend.name]
      state       = ["SUCCESS", "FAILURE", "STOP"]
    }
  })
}

resource "aws_cloudwatch_event_target" "pipeline_state" {
  rule = aws_cloudwatch_event_rule.pipeline_state.name
  arn  = aws_sns_topic.runtime_alerts.arn
}

resource "aws_cloudwatch_event_target" "codedeploy_state" {
  rule = aws_cloudwatch_event_rule.codedeploy_state.name
  arn  = aws_sns_topic.runtime_alerts.arn
}

data "aws_iam_policy_document" "runtime_alerts_topic" {
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
    resources = [aws_sns_topic.runtime_alerts.arn]

    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
  }

  statement {
    sid       = "EventBridgePublish"
    effect    = "Allow"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.runtime_alerts.arn]

    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values = [
        aws_cloudwatch_event_rule.pipeline_state.arn,
        aws_cloudwatch_event_rule.codedeploy_state.arn,
      ]
    }
  }
}

resource "aws_sns_topic_policy" "runtime_alerts" {
  arn    = aws_sns_topic.runtime_alerts.arn
  policy = data.aws_iam_policy_document.runtime_alerts_topic.json
}

output "delivery" {
  description = "CI/CD pipeline, deploy, notification, and operator attachment identifiers"
  value = {
    pipelines               = local.delivery_pipeline_names
    codebuild_projects      = local.codebuild_projects
    codedeploy_application  = aws_codedeploy_app.backend.name
    codedeploy_group        = aws_codedeploy_deployment_group.backend.deployment_group_name
    discord_secret_arn      = aws_secretsmanager_secret.discord_webhook.arn
    operator_policy_arn     = aws_iam_policy.pipeline_operator.arn
    operator_user_names     = sort(tolist(var.pipeline_operator_user_names))
    automatic_main_delivery = var.integrated_pipeline_detect_changes
  }
}
