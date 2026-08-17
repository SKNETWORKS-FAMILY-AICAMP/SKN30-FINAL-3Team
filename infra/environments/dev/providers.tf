provider "aws" {
  region              = var.aws_region
  allowed_account_ids = [var.target_account_id]

  assume_role {
    role_arn     = "arn:aws:iam::${var.target_account_id}:role/TerraformOperatorRole"
    session_name = "terraform-dev"
    duration     = "1h"
  }

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = "dev"
      ManagedBy   = "Terraform"
      Owner       = var.owner
      ExpiresAt   = var.expires_at
    }
  }
}
