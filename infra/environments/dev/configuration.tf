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
      description = "Container for flat AI_*_API_KEY JSON populated outside Terraform"
    }
  }

  runpod_secret_names = {
    operator_api_key = {
      name        = "/${local.name_prefix}/runpod/operator-api-key"
      description = "Container for the RunPod read-write operator API key populated outside Terraform"
    }
    ghcr_registry = {
      name        = "/${local.name_prefix}/runpod/ghcr-registry"
      description = "Read-only GHCR credentials for AWS GPU hosts; RunPod registry credentials remain Console-managed"
    }
  }

  application_environment = {
    backend = merge({
      APP_ENV                               = "dev"
      APP_HOST                              = "0.0.0.0"
      APP_PORT                              = "8000"
      AUTH_DEVELOPMENT_ENABLED              = tostring(local.development_auth_enabled)
      AUTH_SESSION_ABSOLUTE_TIMEOUT_MINUTES = "720"
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
      F3_ALLOW_SYNTHETIC_PROTOTYPE = "true"
      # migration 021과 통합 검증 후 자동 접수를 활성화한다. 신규 연산 자원은 추가하지 않는다.
      F3_AUTO_JUDGMENT_ENABLED = "false"
      F3_AUTO_DEBOUNCE_SECONDS = "3"
      F3_AUTO_BATCH_SIZE       = "20"
    }, local.development_auth_identity_environment)
    ai = merge({
      # Shared provider/model choices are validated together in general-model.tf; restart after reviewed apply.
      AI_GENERAL_PROVIDER        = var.general_model_selection.provider
      AI_GENERAL_MODEL           = var.general_model_selection.model
      AI_REQUEST_TIMEOUT_SECONDS = "60"
      }, var.general_model_selection.provider == "bedrock" ? {
      # Bedrock only: ap-northeast-2, matching this root's runtime role; omitted for API-key providers.
      AI_GENERAL_AWS_REGION = var.general_model_selection.aws_region
    } : {})
  }

  ai_vllm_endpoint_set_bootstrap = {
    revision        = 0
    status          = "offline"
    pod_id          = null
    sllm_release_id = null
    sllm_base_url   = null
    stt_base_url    = null
    updated_at      = "1970-01-01T00:00:00Z"
  }

  runpod_control_set_bootstrap = {
    schema_version   = 2
    status           = "uninitialized"
    registry_auth_id = null
    template_id      = null
    image            = null
    updated_at       = "1970-01-01T00:00:00Z"
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

resource "aws_secretsmanager_secret" "runpod" {
  for_each = local.runpod_secret_names

  name                    = each.value.name
  description             = each.value.description
  recovery_window_in_days = 7

  tags = {
    Name = each.value.name
  }
}

removed {
  from = aws_secretsmanager_secret_version.ai_provider

  lifecycle {
    destroy = false
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

resource "aws_ssm_parameter" "ai_vllm_endpoint_set" {
  name        = "/${local.name_prefix}/ai/AI_VLLM_ENDPOINT_SET"
  description = "Operational container for the atomic ephemeral RunPod SLLM and STT endpoint set"
  type        = "String"
  value       = jsonencode(local.ai_vllm_endpoint_set_bootstrap)
  tier        = "Standard"

  lifecycle {
    # The RunPod runbook owns this operational value so both URLs cut over atomically.
    ignore_changes = [value]
  }

  tags = {
    Name = "/${local.name_prefix}/ai/AI_VLLM_ENDPOINT_SET"
  }
}

resource "aws_ssm_parameter" "runpod_control_set" {
  name        = "/${local.name_prefix}/runpod/RUNPOD_CONTROL_SET"
  description = "Non-sensitive registration of Console-managed RunPod resource IDs and image digest"
  type        = "String"
  value       = jsonencode(local.runpod_control_set_bootstrap)
  tier        = "Standard"

  lifecycle {
    # The reviewed RunPod operator commands own this resumable operational value.
    ignore_changes = [value]
  }

  tags = {
    Name = "/${local.name_prefix}/runpod/RUNPOD_CONTROL_SET"
  }
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
  value = merge(
    { for setting, parameter in aws_ssm_parameter.application : setting => parameter.name },
    { ai_ai_vllm_endpoint_set = aws_ssm_parameter.ai_vllm_endpoint_set.name },
  )
}
