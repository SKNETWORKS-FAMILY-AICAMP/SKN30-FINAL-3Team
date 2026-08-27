target_account_id            = "000000000000"
expires_at                   = "2026-09-23"
pipeline_operator_user_names = ["example-infra-user"]

# 계정 생성 전에는 null을 유지해 Backend 개발 세션 경로와 Frontend 버튼을 모두 닫는다.
development_auth = null

# 공유 dev DB에 고정 합성 계정을 생성한 뒤 출력값으로 대체한다.
# development_auth = {
#   brokerage_id = 1
#   login_id      = "developer"
# }
