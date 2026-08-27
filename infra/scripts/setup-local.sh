#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
infra_dir="$(cd -- "$script_dir/.." && pwd)"

aws_region="ap-northeast-2"
project_name="skn30-final-3team"
bootstrap_profile="skn30-bootstrap"
session_profile="skn30-session"
target_account_id=""
expires_at=""
skip_login=false
force=false

usage() {
  cat <<'EOF'
Usage:
  infra/scripts/setup-local.sh --account-id <12자리-ID> --expires-at <YYYY-MM-DD> [options]

Options:
  --account-id ID            연결할 AWS 계정 ID (필수)
  --expires-at DATE          dev 환경 종료 예정일 (필수)
  --project-name NAME        프로젝트 이름 (기본: skn30-final-3team)
  --bootstrap-profile NAME   aws login profile (기본: skn30-bootstrap)
  --session-profile NAME     Terraform credential profile (기본: skn30-session)
  --skip-login               이미 로그인된 세션을 사용
  --force                    다른 내용의 로컬 backend.hcl을 덮어씀(dev.tfvars는 항상 보존)
  -h, --help                 도움말 출력

이 스크립트는 로컬 profile, backend.hcl, dev.tfvars, Terraform init과
읽기 전용 연결 검증만 수행합니다. AWS 자원 생성과 terraform apply는 실행하지 않습니다.
EOF
}

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

read_tfvars_string() {
  local target="$1"
  local name="$2"
  local values=()

  mapfile -t values < <(
    sed -nE \
      "s~^[[:space:]]*${name}[[:space:]]*=[[:space:]]*\"([^\"]*)\"[[:space:]]*((#|//).*)?$~\\1~p" \
      "$target"
  )
  ((${#values[@]} == 1)) ||
    fail "$target에는 하나의 문자열 ${name} 할당이 필요합니다."
  printf '%s' "${values[0]}"
}

validate_existing_dev_tfvars() {
  local target="$infra_dir/environments/dev/dev.tfvars"
  local existing_account_id
  local existing_expires_at

  [[ -e "$target" ]] || return 0
  [[ -f "$target" && ! -L "$target" ]] ||
    fail "$target은 symbolic link가 아닌 일반 파일이어야 합니다."

  existing_account_id="$(read_tfvars_string "$target" target_account_id)"
  existing_expires_at="$(read_tfvars_string "$target" expires_at)"
  [[ "$existing_account_id" == "$target_account_id" ]] ||
    fail "$target의 target_account_id가 요청값과 다릅니다. --force로 덮어쓰지 않으므로 파일을 직접 검토하세요."
  [[ "$existing_expires_at" == "$expires_at" ]] ||
    fail "$target의 expires_at이 요청값과 다릅니다. --force로 덮어쓰지 않으므로 파일을 직접 검토하세요."
}

while (($# > 0)); do
  case "$1" in
    --account-id)
      (($# >= 2)) || fail "--account-id 값이 필요합니다."
      target_account_id="$2"
      shift 2
      ;;
    --expires-at)
      (($# >= 2)) || fail "--expires-at 값이 필요합니다."
      expires_at="$2"
      shift 2
      ;;
    --project-name)
      (($# >= 2)) || fail "--project-name 값이 필요합니다."
      project_name="$2"
      shift 2
      ;;
    --bootstrap-profile)
      (($# >= 2)) || fail "--bootstrap-profile 값이 필요합니다."
      bootstrap_profile="$2"
      shift 2
      ;;
    --session-profile)
      (($# >= 2)) || fail "--session-profile 값이 필요합니다."
      session_profile="$2"
      shift 2
      ;;
    --skip-login)
      skip_login=true
      shift
      ;;
    --force)
      force=true
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      fail "알 수 없는 옵션입니다: $1"
      ;;
  esac
done

[[ "$target_account_id" =~ ^[0-9]{12}$ ]] || fail "--account-id는 12자리여야 합니다."
[[ "$expires_at" =~ ^20[0-9]{2}-(0[1-9]|1[0-2])-([0-2][0-9]|3[0-1])$ ]] ||
  fail "--expires-at은 YYYY-MM-DD 형식이어야 합니다."
[[ "$project_name" =~ ^[a-z0-9-]{3,24}$ ]] ||
  fail "--project-name은 3~24자의 소문자, 숫자, 하이픈만 사용할 수 있습니다."
[[ "$bootstrap_profile" =~ ^[A-Za-z0-9_.-]+$ ]] ||
  fail "--bootstrap-profile에는 영문자, 숫자, 점, 밑줄, 하이픈만 사용할 수 있습니다."
[[ "$session_profile" =~ ^[A-Za-z0-9_.-]+$ ]] ||
  fail "--session-profile에는 영문자, 숫자, 점, 밑줄, 하이픈만 사용할 수 있습니다."

# 기존 계정 블록을 보존하고 불일치를 AWS 로그인·로컬 파일 변경 전에 차단한다.
validate_existing_dev_tfvars

command -v aws >/dev/null 2>&1 || fail "AWS CLI가 필요합니다."
command -v terraform >/dev/null 2>&1 || fail "Terraform이 필요합니다."

for profile in "$bootstrap_profile" "$session_profile"; do
  configured_access_key="$(aws configure get aws_access_key_id --profile "$profile" 2>/dev/null || true)"
  [[ -z "$configured_access_key" ]] ||
    fail "$profile profile에 정적 access key가 있습니다. 제거하고 aws login을 사용하세요."
done

ensure_profile_value() {
  local profile="$1"
  local key="$2"
  local value="$3"
  local current

  current="$(aws configure get "$key" --profile "$profile" 2>/dev/null || true)"
  if [[ "$current" != "$value" ]]; then
    aws configure set "$key" "$value" --profile "$profile"
  fi
}

ensure_profile_value "$bootstrap_profile" region "$aws_region"
ensure_profile_value "$session_profile" region "$aws_region"
ensure_profile_value \
  "$session_profile" \
  credential_process \
  "aws configure export-credentials --profile $bootstrap_profile --format process"

if [[ "$skip_login" == false ]]; then
  printf 'AWS 브라우저 로그인과 MFA를 진행합니다.\n'
  aws login --profile "$bootstrap_profile"
fi

caller_account="$(aws sts get-caller-identity \
  --profile "$bootstrap_profile" \
  --query Account \
  --output text)"
caller_arn="$(aws sts get-caller-identity \
  --profile "$bootstrap_profile" \
  --query Arn \
  --output text)"

[[ "$caller_account" == "$target_account_id" ]] ||
  fail "로그인 계정($caller_account)이 대상 계정($target_account_id)과 다릅니다."
[[ "$caller_arn" != *":root" ]] || fail "root 자격 증명은 사용할 수 없습니다."

TARGET_ACCOUNT_ID="$target_account_id" \
  AWS_PROFILE="$session_profile" \
  "$script_dir/preflight.sh"

state_bucket="${project_name}-tfstate-${target_account_id}-${aws_region}"
operator_role_arn="arn:aws:iam::${target_account_id}:role/TerraformOperatorRole"

backend_content="$(printf '%s\n' \
  "bucket  = \"$state_bucket\"" \
  "profile = \"$session_profile\"" \
  'assume_role = {' \
  "  role_arn     = \"$operator_role_arn\"" \
  '  session_name = "terraform-state"' \
  '  duration     = "1h"' \
  '}')"

dev_tfvars_content="$(printf '%s\n' \
  "target_account_id = \"$target_account_id\"" \
  "expires_at        = \"$expires_at\"" \
  "" \
  "development_auth = null")"

write_local_file() {
  local target="$1"
  local content="$2"
  local temp_file

  temp_file="$(mktemp "${target}.tmp.XXXXXX")"
  chmod 600 "$temp_file"
  printf '%s\n' "$content" >"$temp_file"

  if [[ -f "$target" ]] && cmp -s "$temp_file" "$target"; then
    rm "$temp_file"
    printf '유지: %s\n' "$target"
    return
  fi

  if [[ -e "$target" && "$force" == false ]]; then
    rm "$temp_file"
    fail "$target 파일 내용이 다릅니다. 검토 후 --force로 다시 실행하세요."
  fi

  mv "$temp_file" "$target"
  printf '생성: %s\n' "$target"
}

ensure_dev_tfvars() {
  local target="$infra_dir/environments/dev/dev.tfvars"

  if [[ -e "$target" ]]; then
    validate_existing_dev_tfvars
    printf '유지: %s\n' "$target"
    return
  fi

  # --force와 무관하게 이 파일은 없을 때만 생성한다.
  write_local_file "$target" "$dev_tfvars_content"
}

write_local_file "$infra_dir/bootstrap/backend.hcl" "$backend_content"
write_local_file "$infra_dir/environments/dev/backend.hcl" "$backend_content"
ensure_dev_tfvars

AWS_PROFILE="$session_profile" terraform -chdir="$infra_dir/bootstrap" init \
  -input=false \
  -reconfigure \
  -backend-config=backend.hcl

TARGET_ACCOUNT_ID="$target_account_id" \
  EXPIRES_AT="$expires_at" \
  PROJECT_NAME="$project_name" \
  AWS_PROFILE="$session_profile" \
  "$script_dir/verify-account-link.sh"

printf '\n로컬 AWS-Terraform 연결 설정이 완료됐습니다.\n'
printf 'AWS 자원은 생성하거나 변경하지 않았습니다.\n'
