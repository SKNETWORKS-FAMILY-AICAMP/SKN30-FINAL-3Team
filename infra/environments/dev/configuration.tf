locals {
  application_secret_names = {
    backend_runtime_database = {
      name        = "/${local.name_prefix}/backend/runtime-database-url"
      description = "Container for structured Backend runtime database credentials; the value is populated outside Terraform"
    }
    backend_migration_database = {
      name        = "/${local.name_prefix}/backend/migration-database-url"
      description = "Deprecated empty compatibility container; migrations use IAM database authentication"
    }
    ai_provider = {
      name        = "/${local.name_prefix}/ai/provider-api-keys"
      description = "Container for AI_OPENAI_API_KEY, AI_VLLM_LLM_API_KEY, and AI_VLLM_EMBEDDING_API_KEY; values are populated outside Terraform"
    }
  }

  application_parameters = {
    backend_app_env                       = { path = "backend/APP_ENV", value = "prod" }
    backend_app_host                      = { path = "backend/APP_HOST", value = "0.0.0.0" }
    backend_app_openapi_enabled           = { path = "backend/APP_OPENAPI_ENABLED", value = "false" }
    backend_app_port                      = { path = "backend/APP_PORT", value = "8000" }
    backend_auth_development_enabled      = { path = "backend/AUTH_DEVELOPMENT_ENABLED", value = "false" }
    backend_auth_session_absolute_minutes = { path = "backend/AUTH_SESSION_ABSOLUTE_TIMEOUT_MINUTES", value = "10080" }
    backend_auth_session_cookie_name      = { path = "backend/AUTH_SESSION_COOKIE_NAME", value = "brokerage_session" }
    backend_auth_session_idle_minutes     = { path = "backend/AUTH_SESSION_IDLE_TIMEOUT_MINUTES", value = "1440" }
    backend_auth_session_last_seen        = { path = "backend/AUTH_SESSION_LAST_SEEN_UPDATE_SECONDS", value = "300" }
    backend_db_pool_max_overflow          = { path = "backend/DB_POOL_MAX_OVERFLOW", value = "5" }
    backend_db_pool_size                  = { path = "backend/DB_POOL_SIZE", value = "5" }
    backend_db_pool_timeout               = { path = "backend/DB_POOL_TIMEOUT_SECONDS", value = "30" }
    backend_db_target                     = { path = "backend/DB_TARGET", value = "production" }
    backend_http_allowed_hosts            = { path = "backend/HTTP_ALLOWED_HOSTS", value = jsonencode([aws_lb.app.dns_name, "localhost", "127.0.0.1"]) }
    backend_http_cors_allowed_origins     = { path = "backend/HTTP_CORS_ALLOWED_ORIGINS", value = "[]" }
    backend_log_format                    = { path = "backend/LOG_FORMAT", value = "json" }
    backend_log_level                     = { path = "backend/LOG_LEVEL", value = "INFO" }
    backend_f3_allow_synthetic_prototype  = { path = "backend/F3_ALLOW_SYNTHETIC_PROTOTYPE", value = "false" }
    backend_worker_enabled                = { path = "backend/WORKER_ENABLED", value = "false" }
    ai_openai_base_url                    = { path = "ai/AI_OPENAI_BASE_URL", value = "https://api.openai.com/v1" }
    ai_request_timeout_seconds            = { path = "ai/AI_REQUEST_TIMEOUT_SECONDS", value = "60" }
  }
}

resource "aws_secretsmanager_secret" "application" {
  for_each = local.application_secret_names

  name                    = each.value.name
  description             = each.value.description
  recovery_window_in_days = 7

  tags = {
    Name = each.value.name
  }
}

resource "aws_ssm_parameter" "application" {
  for_each = local.application_parameters

  name        = "/${local.name_prefix}/${each.value.path}"
  description = "Versioned non-sensitive ${replace(each.value.path, "/", " ")} setting"
  type        = "String"
  value       = each.value.value
  tier        = "Standard"

  tags = {
    Name = "/${local.name_prefix}/${each.value.path}"
  }
}

output "application_secret_arns" {
  description = "런타임 IAM과 배포 주입 구성이 참조할 빈 application secret container ARN"
  value       = { for purpose, secret in aws_secretsmanager_secret.application : purpose => secret.arn }
}

output "application_parameter_names" {
  description = "런타임 설정 주입 구성이 참조할 비민감 SSM parameter 이름"
  value       = { for setting, parameter in aws_ssm_parameter.application : setting => parameter.name }
}
