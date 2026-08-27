locals {
  development_auth_enabled = var.development_auth != null
  development_auth_identity_environment = var.development_auth == null ? tomap({}) : tomap({
    AUTH_DEVELOPMENT_BROKERAGE_ID = tostring(var.development_auth.brokerage_id)
    AUTH_DEVELOPMENT_LOGIN_ID     = trimspace(var.development_auth.login_id)
  })

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
      description = "AI provider API keys managed from the ignored secrets.auto.tfvars input"
    }
  }

  application_environment = {
    backend = merge({
      APP_ENV                               = "dev"
      APP_HOST                              = "0.0.0.0"
      APP_OPENAPI_ENABLED                   = "false"
      APP_PORT                              = "8000"
      AUTH_CSRF_COOKIE_NAME                 = "brokerage_csrf"
      AUTH_DEVELOPMENT_ENABLED              = tostring(local.development_auth_enabled)
      AUTH_SESSION_ABSOLUTE_TIMEOUT_MINUTES = "720"
      AUTH_SESSION_COOKIE_NAME              = "brokerage_session"
      AUTH_SESSION_IDLE_TIMEOUT_MINUTES     = "30"
      AUTH_SESSION_LAST_SEEN_UPDATE_SECONDS = "300"
      DB_POOL_MAX_OVERFLOW                  = "5"
      DB_POOL_SIZE                          = "5"
      DB_POOL_TIMEOUT_SECONDS               = "30"
      DB_TARGET                             = "development"
      HTTP_ALLOWED_HOSTS = jsonencode(concat(
        aws_lb.app[*].dns_name,
        ["localhost", "127.0.0.1"],
      ))
      HTTP_CORS_ALLOWED_ORIGINS    = "[]"
      LOG_FORMAT                   = "json"
      LOG_LEVEL                    = "INFO"
      WORKER_ENABLED               = "false"
      WORKER_READY_FILE            = "/tmp/brokerage-worker-ready"
      F3_ALLOW_SYNTHETIC_PROTOTYPE = "false"
    }, local.development_auth_identity_environment)
    ai = {
      AI_OPENAI_BASE_URL         = "https://api.openai.com/v1"
      AI_REQUEST_TIMEOUT_SECONDS = "60"
      AI_VLLM_LLM_BASE_URL       = "https://xkgavic14hanqr-8001.proxy.runpod.net/v1"
      AI_VLLM_STT_BASE_URL       = "https://xkgavic14hanqr-8002.proxy.runpod.net/v1"
    }
  }

  application_parameters = merge([
    for namespace, values in local.application_environment : {
      for name, value in values : "${namespace}_${lower(name)}" => {
        path  = "${namespace}/${name}"
        value = value
      }
    }
  ]...)
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

resource "aws_secretsmanager_secret_version" "ai_provider" {
  secret_id                = aws_secretsmanager_secret.application["ai_provider"].id
  secret_string_wo         = jsonencode(var.ai_provider_api_keys)
  secret_string_wo_version = var.ai_provider_secret_version
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

moved {
  from = aws_ssm_parameter.application["ai_openai_base_url"]
  to   = aws_ssm_parameter.application["ai_ai_openai_base_url"]
}

moved {
  from = aws_ssm_parameter.application["ai_request_timeout_seconds"]
  to   = aws_ssm_parameter.application["ai_ai_request_timeout_seconds"]
}

moved {
  from = aws_ssm_parameter.application["backend_auth_session_absolute_minutes"]
  to   = aws_ssm_parameter.application["backend_auth_session_absolute_timeout_minutes"]
}

moved {
  from = aws_ssm_parameter.application["backend_auth_session_idle_minutes"]
  to   = aws_ssm_parameter.application["backend_auth_session_idle_timeout_minutes"]
}

moved {
  from = aws_ssm_parameter.application["backend_auth_session_last_seen"]
  to   = aws_ssm_parameter.application["backend_auth_session_last_seen_update_seconds"]
}

moved {
  from = aws_ssm_parameter.application["backend_db_pool_timeout"]
  to   = aws_ssm_parameter.application["backend_db_pool_timeout_seconds"]
}

output "application_secret_arns" {
  description = "런타임 IAM과 배포 주입 구성이 참조할 application secret container ARN"
  value       = { for purpose, secret in aws_secretsmanager_secret.application : purpose => secret.arn }
}

output "application_parameter_names" {
  description = "런타임 설정 주입 구성이 참조할 비민감 SSM parameter 이름"
  value       = { for setting, parameter in aws_ssm_parameter.application : setting => parameter.name }
}
