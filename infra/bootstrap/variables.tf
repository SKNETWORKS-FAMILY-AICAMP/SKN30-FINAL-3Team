variable "target_account_id" {
  description = "전용 AWS 계정의 12자리 ID"
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.target_account_id))
    error_message = "target_account_id는 12자리 AWS 계정 ID여야 합니다."
  }
}

variable "aws_region" {
  description = "모든 프로젝트 자원을 관리할 AWS 리전"
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

variable "operator_user_arns" {
  description = "TerraformOperatorRole을 assume할 수 있는 개인 IAM 사용자 ARN 집합"
  type        = set(string)

  validation {
    condition = length(var.operator_user_arns) > 0 && alltrue([
      for arn in var.operator_user_arns :
      can(regex("^arn:(aws|aws-us-gov|aws-cn):iam::[0-9]{12}:user/.+$", arn))
    ])
    error_message = "operator_user_arns에는 개인 IAM 사용자 ARN을 하나 이상 지정해야 합니다."
  }
}

variable "create_budget" {
  description = "현재 계정에서 AWS Budget 생성을 비활성화하는 호환 입력"
  type        = bool
  default     = false

  validation {
    condition     = var.create_budget == false
    error_message = "현재 계정에서는 AWS Billing 관련 서비스를 사용할 수 없으므로 create_budget은 false여야 합니다."
  }
}

variable "budget_notification_email" {
  description = "create_budget=false에서 사용하지 않는 기존 bootstrap 호환 입력"
  type        = string
  sensitive   = true

  validation {
    condition     = can(regex("^[^[:space:]@]+@[^[:space:]@]+[.][^[:space:]@]+$", var.budget_notification_email))
    error_message = "budget_notification_email에 유효한 이메일 형식을 지정해야 합니다."
  }
}

variable "monthly_budget_amount" {
  description = "create_budget=false에서 사용하지 않는 기존 bootstrap 호환 입력"
  type        = number

  validation {
    condition     = var.monthly_budget_amount > 0
    error_message = "monthly_budget_amount는 0보다 커야 합니다."
  }
}

variable "expires_at" {
  description = "기존 IAM 운영 권한과 개발 환경 종료 예정일(YYYY-MM-DD)"
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

variable "use_operator_role" {
  description = "TerraformOperatorRole 생성 후 provider가 해당 역할을 assume할지 여부; 최초 local bootstrap에서만 false"
  type        = bool
  default     = true
}
