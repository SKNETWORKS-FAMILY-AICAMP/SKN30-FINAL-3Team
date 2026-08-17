output "verified_account_id" {
  description = "AWS가 검증한 현재 계정 ID"
  value       = data.aws_caller_identity.current.account_id

  precondition {
    condition     = data.aws_caller_identity.current.account_id == var.target_account_id
    error_message = "현재 자격 증명의 AWS 계정이 target_account_id와 다릅니다."
  }

  precondition {
    condition = alltrue([
      for arn in var.operator_user_arns : split(":", arn)[4] == var.target_account_id
    ])
    error_message = "operator_user_arns의 모든 사용자는 target_account_id 계정에 속해야 합니다."
  }
}

output "verified_region" {
  description = "AWS provider가 사용하는 리전"
  value       = data.aws_region.current.region

  precondition {
    condition     = data.aws_region.current.region == "ap-northeast-2"
    error_message = "현재 AWS provider 리전이 ap-northeast-2가 아닙니다."
  }
}

output "state_bucket_name" {
  description = "Terraform 원격 state S3 bucket 이름"
  value       = aws_s3_bucket.terraform_state.id
}

output "terraform_operator_role_arn" {
  description = "승인된 개인 IAM 사용자가 aws login 세션으로 assume하는 Terraform 역할 ARN"
  value       = aws_iam_role.terraform_operator.arn
}

output "budget_name" {
  description = "생성된 월 AWS 비용 예산 이름; Budget을 비활성화하면 null"
  value       = try(aws_budgets_budget.monthly[0].name, null)
}
