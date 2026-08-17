provider "aws" {
  region              = var.aws_region
  allowed_account_ids = [var.target_account_id]

  dynamic "assume_role" {
    for_each = var.use_operator_role ? [1] : []

    content {
      role_arn     = "arn:aws:iam::${var.target_account_id}:role/TerraformOperatorRole"
      session_name = "terraform-bootstrap"
      duration     = "1h"
    }
  }

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = "account"
      ManagedBy   = "Terraform"
      Owner       = var.owner
      ExpiresAt   = var.expires_at
    }
  }
}

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
data "aws_region" "current" {}
