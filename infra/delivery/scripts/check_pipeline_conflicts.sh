#!/usr/bin/env bash
set -euo pipefail

: "${CURRENT_PIPELINE:?CURRENT_PIPELINE is required}"
: "${OTHER_PIPELINES:?OTHER_PIPELINES is required}"

for pipeline in ${OTHER_PIPELINES}; do
  status="$(aws codepipeline list-pipeline-executions     --pipeline-name "${pipeline}"     --max-results 1     --query 'pipelineExecutionSummaries[0].status'     --output text)"
  if [[ "${status}" == "InProgress" || "${status}" == "Stopping" ]]; then
    echo "${CURRENT_PIPELINE} is blocked because ${pipeline} is ${status}" >&2
    exit 1
  fi
done

if [[ -n "${BACKEND_ORIGIN:-}" ]]; then
  curl -fsS --retry 3 "${BACKEND_ORIGIN}/health/live" >/dev/null
  curl -fsS --retry 3 "${BACKEND_ORIGIN}/health/ready" >/dev/null
fi

printf 'pipeline=%s revision=%s execution=%s admission=passed\n'   "${PIPELINE_KIND:-unknown}"   "${CODEBUILD_RESOLVED_SOURCE_VERSION:-unknown}"   "${PIPELINE_EXECUTION_ID:-unknown}"
