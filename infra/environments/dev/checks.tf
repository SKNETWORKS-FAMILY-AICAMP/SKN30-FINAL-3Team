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
