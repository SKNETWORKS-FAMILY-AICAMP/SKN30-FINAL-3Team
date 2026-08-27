variable "target_account_id" {
  description = "전용 AWS 계정의 12자리 ID"
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.target_account_id))
    error_message = "target_account_id는 12자리 AWS 계정 ID여야 합니다."
  }
}

variable "aws_region" {
  description = "개발 환경 AWS 리전"
  type        = string
  default     = "ap-northeast-2"

  validation {
    condition     = var.aws_region == "ap-northeast-2"
    error_message = "이 프로젝트는 ap-northeast-2에서만 실행할 수 있습니다."
  }
}

variable "project_name" {
  description = "이름과 태그에 사용할 프로젝트 식별자"
  type        = string
  default     = "skn30-final-3team"

  validation {
    condition     = can(regex("^[a-z0-9-]{3,24}$", var.project_name))
    error_message = "project_name은 3~24자의 소문자, 숫자, 하이픈만 사용할 수 있습니다."
  }
}

variable "expires_at" {
  description = "개발 환경 종료 예정일(YYYY-MM-DD)"
  type        = string

  validation {
    condition     = can(regex("^20[0-9]{2}-(0[1-9]|1[0-2])-([0-2][0-9]|3[0-1])$", var.expires_at))
    error_message = "expires_at은 YYYY-MM-DD 형식이어야 합니다."
  }

  validation {
    condition     = var.expires_at == "2026-09-23"
    error_message = "dev 환경의 ExpiresAt은 승인된 종료일인 2026-09-23이어야 합니다."
  }
}

variable "owner" {
  description = "비용 및 운영 책임 태그"
  type        = string
  default     = "infra-team"
}

variable "dev_edge_enabled" {
  description = "dev ALB·CloudFront API edge를 활성화할지 여부; deep lifecycle 전용 명령에서만 false로 오버라이드"
  type        = bool
  default     = true
}

variable "development_auth" {
  description = "공개 합성 dev 세션에 사용할 고정 계정; null이면 Backend 경로와 Frontend 버튼을 모두 비활성화"
  type = object({
    brokerage_id = number
    login_id     = string
  })
  default   = null
  nullable  = true
  sensitive = false

  validation {
    condition = var.development_auth == null ? true : (
      var.development_auth.brokerage_id >= 1 &&
      var.development_auth.brokerage_id == floor(var.development_auth.brokerage_id) &&
      length(trimspace(var.development_auth.login_id)) >= 1 &&
      length(trimspace(var.development_auth.login_id)) <= 100
    )
    error_message = "development_auth.brokerage_id는 1 이상의 정수이고 login_id는 공백 제거 후 1~100자여야 합니다."
  }
}

variable "pipeline_operator_user_names" {
  description = "Delivery Pipeline을 수동 운영할 기존 계정 IAM 사용자 이름 집합"
  type        = set(string)

  validation {
    condition = length(var.pipeline_operator_user_names) > 0 && alltrue([
      for name in var.pipeline_operator_user_names :
      can(regex("^[A-Za-z0-9+=,.@_-]{1,64}$", name))
    ])
    error_message = "pipeline_operator_user_names에는 유효한 기존 IAM 사용자 이름을 하나 이상 지정해야 합니다."
  }
}

variable "github_connection_arn" {
  description = "기존 AVAILABLE 상태 SKN30_FINAL CodeConnections connection ARN"
  type        = string
  default     = "arn:aws:codeconnections:ap-northeast-2:398563707017:connection/54dc394c-1a0c-4a44-a315-dacca88893d8"

  validation {
    condition     = can(regex("^arn:aws:codeconnections:ap-northeast-2:[0-9]{12}:connection/[0-9a-f-]+$", var.github_connection_arn))
    error_message = "github_connection_arn은 ap-northeast-2 CodeConnections ARN이어야 합니다."
  }
}

variable "github_full_repository_id" {
  description = "CodeConnections가 읽는 GitHub owner/repository"
  type        = string
  default     = "SKNETWORKS-FAMILY-AICAMP/SKN30-FINAL-3Team"
}

variable "integrated_pipeline_detect_changes" {
  description = "검증 전 false, 최종 전환 후 통합 pipeline dev 자동 감지는 true"
  type        = bool
  default     = false
}

variable "app_asg_health_check_type" {
  description = "초기 delivery 검증은 EC2, 자동 배포 전환 후 ELB"
  type        = string
  default     = "EC2"

  validation {
    condition     = contains(["EC2", "ELB"], var.app_asg_health_check_type)
    error_message = "app_asg_health_check_type은 EC2 또는 ELB여야 합니다."
  }
}

variable "ai_provider_api_keys" {
  description = "Secrets Manager에 write-only로 반영할 AI provider 환경변수 이름과 API key"
  type        = map(string)
  sensitive   = true
  ephemeral   = true

  validation {
    condition = (
      contains(keys(var.ai_provider_api_keys), "AI_OPENAI_API_KEY") &&
      alltrue([
        for name, value in var.ai_provider_api_keys :
        can(regex("^AI_[A-Z0-9_]+_API_KEY$", name)) &&
        trimspace(value) != "" &&
        length(regexall("[[:space:]]", value)) == 0
      ])
    )
    error_message = "ai_provider_api_keys에는 비어 있지 않은 AI_OPENAI_API_KEY와 AI_*_API_KEY 형식의 키만 지정해야 합니다."
  }
}

variable "ai_provider_secret_version" {
  description = "AI provider key 변경을 Secrets Manager 새 version으로 반영하는 단조 증가 정수"
  type        = number

  validation {
    condition     = var.ai_provider_secret_version >= 1 && var.ai_provider_secret_version == floor(var.ai_provider_secret_version)
    error_message = "ai_provider_secret_version은 1 이상의 정수여야 합니다."
  }
}

variable "discord_webhook_url" {
  description = "Discord 알림 Lambda가 사용할 webhook URL"
  type        = string
  sensitive   = true
  ephemeral   = true

  validation {
    condition = (
      (
        startswith(var.discord_webhook_url, "https://discord.com/api/webhooks/") ||
        startswith(var.discord_webhook_url, "https://discordapp.com/api/webhooks/")
      ) &&
      length(regexall("[[:space:]]", var.discord_webhook_url)) == 0
    )
    error_message = "discord_webhook_url은 Discord HTTPS webhook URL이어야 합니다."
  }
}

variable "discord_webhook_secret_version" {
  description = "Discord webhook 변경을 Secrets Manager 새 version으로 반영하는 단조 증가 정수"
  type        = number

  validation {
    condition     = var.discord_webhook_secret_version >= 1 && var.discord_webhook_secret_version == floor(var.discord_webhook_secret_version)
    error_message = "discord_webhook_secret_version은 1 이상의 정수여야 합니다."
  }
}
