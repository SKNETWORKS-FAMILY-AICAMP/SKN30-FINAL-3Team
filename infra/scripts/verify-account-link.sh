#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
infra_dir="$(cd -- "$script_dir/.." && pwd)"
target_account_id="${TARGET_ACCOUNT_ID:-${1:-}}"
aws_profile="${AWS_PROFILE:-skn30-session}"
project_name="${PROJECT_NAME:-skn30-final-3team}"
backend_config_file="${BACKEND_CONFIG_FILE:-$infra_dir/environments/dev/backend.hcl}"

[[ -n "$target_account_id" ]] || {
  printf 'ERROR: TARGET_ACCOUNT_ID 또는 첫 번째 인자로 계정 ID를 지정하세요.\n' >&2
  exit 1
}

TARGET_ACCOUNT_ID="$target_account_id" AWS_PROFILE="$aws_profile" \
  "$script_dir/preflight.sh"

state_bucket="${project_name}-tfstate-${target_account_id}-ap-northeast-2"

[[ -f "$backend_config_file" ]] || {
  printf 'ERROR: backend 설정 파일이 없습니다: %s\n' "$backend_config_file" >&2
  exit 1
}

operator_role_arn="arn:aws:iam::${target_account_id}:role/TerraformOperatorRole"
read -r operator_access_key operator_secret_key operator_session_token < <(
  aws sts assume-role \
    --profile "$aws_profile" \
    --role-arn "$operator_role_arn" \
    --role-session-name account-link-verify \
    --duration-seconds 3600 \
    --query "Credentials.[AccessKeyId,SecretAccessKey,SessionToken]" \
    --output text
)

operator_aws() {
  AWS_ACCESS_KEY_ID="$operator_access_key" \
    AWS_SECRET_ACCESS_KEY="$operator_secret_key" \
    AWS_SESSION_TOKEN="$operator_session_token" \
    AWS_REGION="ap-northeast-2" \
    aws "$@"
}

operator_aws s3api get-bucket-location --bucket "$state_bucket" >/dev/null
operator_aws s3api get-bucket-versioning --bucket "$state_bucket" >/dev/null
operator_aws s3api get-bucket-encryption --bucket "$state_bucket" >/dev/null
operator_aws s3api get-public-access-block --bucket "$state_bucket" >/dev/null
unset operator_access_key operator_secret_key operator_session_token

terraform -chdir="$infra_dir/environments/dev" init \
  -input=false \
  -reconfigure \
  -backend-config="$backend_config_file"
terraform -chdir="$infra_dir/environments/dev" validate
terraform -chdir="$infra_dir/environments/dev" state pull >/dev/null

printf 'Account link verified; remote dev state is readable and the configuration is valid.\n'
