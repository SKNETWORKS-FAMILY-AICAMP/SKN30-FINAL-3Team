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
    monitor_api_key = {
      name        = "/${local.name_prefix}/runpod/monitor-api-key"
      description = "Container for the RunPod read-only monitoring API key populated outside Terraform"
    }
    ghcr_registry = {
      name        = "/${local.name_prefix}/runpod/ghcr-registry"
      description = "Container for GHCR username and read-only PAT JSON populated outside Terraform"
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
      WORKER_ENABLED               = "true"
      WORKER_READY_FILE            = "/tmp/brokerage-worker-ready"
      F3_ALLOW_SYNTHETIC_PROTOTYPE = "true"
    }, local.development_auth_identity_environment)
    ai = {
      AI_LLM_ENDPOINTS = jsonencode([
        {
          alias      = "general-dev-bedrock"
          provider   = "bedrock"
          aws_region = var.aws_region
        },
      ])
      AI_OPENAI_BASE_URL         = "https://api.openai.com/v1"
      AI_REQUEST_TIMEOUT_SECONDS = "60"
    }
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
    schema_version                = 1
    status                        = "uninitialized"
    generation                    = 0
    registry_auth_id              = null
    template_id                   = null
    image                         = null
    ai_provider_secret_version_id = null
    updated_at                    = "1970-01-01T00:00:00Z"
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
  description = "Non-sensitive RunPod bootstrap generation, immutable resource IDs, image digest, and secret synchronization state"
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
  value = merge(
    { for setting, parameter in aws_ssm_parameter.application : setting => parameter.name },
    { ai_ai_vllm_endpoint_set = aws_ssm_parameter.ai_vllm_endpoint_set.name },
  )
}
