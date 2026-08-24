data "aws_availability_zones" "available" {
  state = "available"

  filter {
    name   = "opt-in-status"
    values = ["opt-in-not-required"]
  }
}

check "target_account" {
  assert {
    condition     = data.aws_caller_identity.current.account_id == var.target_account_id
    error_message = "현재 자격 증명의 AWS 계정이 target_account_id와 다릅니다."
  }
}

check "target_region" {
  assert {
    condition     = data.aws_region.current.region == "ap-northeast-2" && var.aws_region == "ap-northeast-2"
    error_message = "dev 환경은 ap-northeast-2에서만 구성할 수 있습니다."
  }
}

check "availability_zone_count" {
  assert {
    condition     = length(data.aws_availability_zones.available.names) >= 2
    error_message = "ALB와 RDS subnet group을 구성하려면 서로 다른 가용 영역이 2개 이상 필요합니다."
  }
}

check "frontend_api_base_path" {
  assert {
    condition = (
      startswith(local.frontend_api_base_path, "/api/") &&
      !endswith(local.frontend_api_base_path, "/") &&
      !strcontains(local.frontend_api_base_path, "://")
    )
    error_message = "frontend_api_base_path는 /api/ 하위의 trailing slash 없는 same-origin 상대 경로여야 합니다."
  }
}

check "application_environment_names" {
  assert {
    condition = alltrue(flatten([
      for _, values in local.application_environment : [
        for name in keys(values) :
        can(regex("^[A-Z][A-Z0-9_]*$", name)) &&
        !contains(["DB_URL", "DB_MIGRATION_URL"], name) &&
        !startswith(name, "AWS_") &&
        alltrue([
          for suffix in ["_API_KEY", "_PASSWORD", "_PRIVATE_KEY", "_SECRET", "_TOKEN"] :
          !endswith(name, suffix)
        ])
      ]
    ]))
    error_message = "application_environment key는 대문자 환경변수 이름이어야 하며 DB/AWS 예약 이름과 비밀형 suffix를 사용할 수 없습니다."
  }
}

check "application_environment_namespaces_are_disjoint" {
  assert {
    condition = length(setintersection(
      toset(keys(local.application_environment.backend)),
      toset(keys(local.application_environment.ai)),
    )) == 0
    error_message = "backend와 ai 공개 환경변수 key는 중복될 수 없습니다."
  }
}

check "frontend_build_environment" {
  assert {
    condition = alltrue([
      for name, value in local.frontend_build_environment :
      can(regex("^VITE_[A-Z0-9_]+$", name)) && trimspace(value) != ""
    ])
    error_message = "frontend_build_environment는 비어 있지 않은 공개 VITE_* 대문자 환경변수만 포함해야 합니다."
  }
}
