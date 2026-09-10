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

output "sllm_model_bucket_name" {
  description = "SLLM release bundle을 보관하는 private S3 bucket 이름"
  value       = aws_s3_bucket.workload["data_model"].bucket
}

output "runpod_operational_resources" {
  description = "RunPod bootstrap and rotation commands consume these non-secret identifiers"
  value = {
    ai_provider_secret_arn      = aws_secretsmanager_secret.application["ai_provider"].arn
    delivery_discord_secret_arn = aws_secretsmanager_secret.discord_webhook.arn
    alarm_discord_secret_arn    = aws_secretsmanager_secret.alarm_discord_webhook.arn
    runpod_secret_arns          = { for purpose, secret in aws_secretsmanager_secret.runpod : purpose => secret.arn }
    endpoint_parameter_name     = aws_ssm_parameter.ai_vllm_endpoint_set.name
    control_parameter_name      = aws_ssm_parameter.runpod_control_set.name
  }
}
