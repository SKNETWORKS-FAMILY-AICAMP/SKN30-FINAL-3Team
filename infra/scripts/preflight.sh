#!/usr/bin/env bash
set -euo pipefail

target_account_id="${TARGET_ACCOUNT_ID:-${1:-}}"
aws_profile="${AWS_PROFILE:-skn30-session}"
aws_region="${AWS_REGION:-${AWS_DEFAULT_REGION:-ap-northeast-2}}"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

command -v aws >/dev/null 2>&1 || fail "AWS CLI가 필요합니다."
command -v terraform >/dev/null 2>&1 || fail "Terraform이 필요합니다."

aws_version_text="$(aws --version 2>&1)"
aws_version="${aws_version_text#aws-cli/}"
aws_version="${aws_version%% *}"
IFS=. read -r aws_major aws_minor _ <<<"$aws_version"
if ((aws_major < 2 || (aws_major == 2 && aws_minor < 36))); then
  fail "AWS CLI 2.36 이상이 필요합니다. 현재: $aws_version"
fi

terraform_version_text="$(terraform version)"
terraform_first_line="${terraform_version_text%%$'\n'*}"
terraform_version="${terraform_first_line#Terraform v}"
[[ "$terraform_version" == 1.15.* ]] ||
  fail "Terraform 1.15.x가 필요합니다. 현재: $terraform_version"

[[ "$target_account_id" =~ ^[0-9]{12}$ ]] ||
  fail "TARGET_ACCOUNT_ID 또는 첫 번째 인자로 12자리 계정 ID를 지정하세요."
[[ "$aws_region" == "ap-northeast-2" ]] ||
  fail "AWS_REGION은 ap-northeast-2여야 합니다. 현재: $aws_region"

if [[ -n "${AWS_ACCESS_KEY_ID:-}" || -n "${AWS_SECRET_ACCESS_KEY:-}" ]]; then
  fail "환경 변수의 AWS 장기 키를 제거하고 aws login profile을 사용하세요."
fi

configured_access_key="$(aws configure get aws_access_key_id --profile "$aws_profile" 2>/dev/null || true)"
[[ -z "$configured_access_key" ]] ||
  fail "$aws_profile profile의 정적 access key를 제거하고 aws login을 사용하세요."

caller_account="$(aws sts get-caller-identity \
  --profile "$aws_profile" \
  --query Account \
  --output text)"
caller_arn="$(aws sts get-caller-identity \
  --profile "$aws_profile" \
  --query Arn \
  --output text)"

[[ "$caller_account" == "$target_account_id" ]] ||
  fail "현재 계정($caller_account)이 대상 계정($target_account_id)과 다릅니다."
[[ "$caller_arn" != *":root" ]] ||
  fail "root 자격 증명으로 Terraform을 실행할 수 없습니다."

configured_region="$(aws configure get region --profile "$aws_profile" 2>/dev/null || true)"
if [[ -n "$configured_region" && "$configured_region" != "ap-northeast-2" ]]; then
  fail "$aws_profile profile 리전이 ap-northeast-2가 아닙니다: $configured_region"
fi

printf 'AWS account link verified: account=%s region=%s profile=%s principal=%s\n' \
  "$caller_account" "$aws_region" "$aws_profile" "$caller_arn"
