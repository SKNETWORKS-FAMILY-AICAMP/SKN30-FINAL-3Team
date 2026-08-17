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
}

variable "owner" {
  description = "비용 및 운영 책임 태그"
  type        = string
  default     = "infra-team"
}
