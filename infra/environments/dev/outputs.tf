output "verified_account_id" {
  description = "AWS가 검증한 현재 계정 ID"
  value       = data.aws_caller_identity.current.account_id

  precondition {
    condition     = data.aws_caller_identity.current.account_id == var.target_account_id
    error_message = "현재 자격 증명의 AWS 계정이 target_account_id와 다릅니다."
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
