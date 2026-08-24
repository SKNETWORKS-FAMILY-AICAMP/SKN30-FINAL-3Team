#!/usr/bin/env bash
set -euo pipefail

: "${FRONTEND_BUCKET:?FRONTEND_BUCKET is required}"
: "${ARTIFACT_BUCKET:?ARTIFACT_BUCKET is required}"
: "${CLOUDFRONT_DISTRIBUTION_ID:?CLOUDFRONT_DISTRIBUTION_ID is required}"
: "${PIPELINE_EXECUTION_ID:?PIPELINE_EXECUTION_ID is required}"

readonly BACKUP_PREFIX="frontend-releases/${PIPELINE_EXECUTION_ID}"
previous_index=false

restore_previous() {
  status=$?
  if [[ "${status}" -eq 0 ]]; then
    return
  fi
  if [[ "${previous_index}" == true ]]; then
    aws s3 cp "s3://${ARTIFACT_BUCKET}/${BACKUP_PREFIX}/index.html"       "s3://${FRONTEND_BUCKET}/index.html"       --cache-control 'no-cache, no-store, must-revalidate'       --content-type 'text/html'
    aws cloudfront create-invalidation       --distribution-id "${CLOUDFRONT_DISTRIBUTION_ID}"       --paths '/' '/index.html' >/dev/null || true
  fi
  exit "${status}"
}
trap restore_previous EXIT

if aws s3api head-object --bucket "${FRONTEND_BUCKET}" --key index.html >/dev/null 2>&1; then
  previous_index=true
  aws s3 cp "s3://${FRONTEND_BUCKET}/index.html"     "s3://${ARTIFACT_BUCKET}/${BACKUP_PREFIX}/index.html"
fi
aws s3 cp release-manifest.json   "s3://${ARTIFACT_BUCKET}/${BACKUP_PREFIX}/release-manifest.json"

aws s3 sync site/ "s3://${FRONTEND_BUCKET}/"   --exclude 'index.html'   --cache-control 'public,max-age=31536000,immutable'
aws s3 cp site/index.html "s3://${FRONTEND_BUCKET}/index.html"   --cache-control 'no-cache, no-store, must-revalidate'   --content-type 'text/html'

invalidation_id="$(aws cloudfront create-invalidation   --distribution-id "${CLOUDFRONT_DISTRIBUTION_ID}"   --paths '/' '/index.html'   --query 'Invalidation.Id'   --output text)"
aws cloudfront wait invalidation-completed   --distribution-id "${CLOUDFRONT_DISTRIBUTION_ID}"   --id "${invalidation_id}"
trap - EXIT
