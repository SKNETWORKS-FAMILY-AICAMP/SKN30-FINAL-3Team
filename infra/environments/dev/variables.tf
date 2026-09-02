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

variable "runpod_monitor_interval_minutes" {
  description = "읽기 전용 RunPod 감시 Lambda 실행 주기(분)"
  type        = number
  default     = 30

  validation {
    condition = (
      var.runpod_monitor_interval_minutes >= 5 &&
      var.runpod_monitor_interval_minutes <= 60 &&
      var.runpod_monitor_interval_minutes == floor(var.runpod_monitor_interval_minutes) &&
      var.runpod_monitor_interval_minutes % 5 == 0
    )
    error_message = "runpod_monitor_interval_minutes는 5~60 사이의 5분 단위 정수여야 합니다."
  }
}

variable "runpod_runtime_warning_hours" {
  description = "공유 RunPod가 연속 실행될 때 경고할 시간"
  type        = number
  default     = 8

  validation {
    condition = (
      var.runpod_runtime_warning_hours >= 1 &&
      var.runpod_runtime_warning_hours <= 24 &&
      var.runpod_runtime_warning_hours == floor(var.runpod_runtime_warning_hours)
    )
    error_message = "runpod_runtime_warning_hours는 1~24 사이의 정수여야 합니다."
  }
}
