---
status: 결정
updated: 2026-09-01
---

# CloudWatch Alarm 장애 대응 Runbook

이 문서는 공유 dev 환경의 CloudWatch Alarm Discord 메시지를 받은 개발자가 조사할 순서를 정한다.
Discord의 최근 오류는 **알람 시각 주변에서 가장 최근에 일치한 안전 로그 1건**이며 직접 원인으로
확정된 로그가 아니다.

## 첫 확인 순서

1. `state`, `changed at`, `module`과 `reason`을 확인한다.
2. `Alarm` 링크에서 임계값, 최근 datapoint와 상태 전이 시각을 확인한다.
3. 애플리케이션 알람이면 `Logs Insights` 링크를 열어 미리 선택된 로그 그룹과
   `StateChangeTime ± 10분` 쿼리를 실행한다. 메시지의 1건만으로 원인을 확정하지 말고 필요하면
   `limit 20`으로 늘려 앞뒤 이벤트를 확인한다.
4. `request_id` 또는 `run_id`가 있으면 같은 상관키로 API·Worker 로그를 좁힌다.
5. 조치 뒤 datapoint가 정상화되고 `OK` 상태 전이가 한 번 도착하는지 확인한다.

`OK` 알림에서는 Lambda가 Logs Insights API를 실행하지 않는다. 링크는 후속 확인을 위해 유지한다.
Discord 전송 자체가 실패하면 SNS가 재시도하므로 동일 상태 알림이 중복될 수 있다.

## 애플리케이션 알람

| 정확한 alarm name | module | 자동 조회 대상 | 조사 기준 |
|---|---|---|---|
| `skn30-final-3team-dev-backend-unhandled-errors` | `backend` | API의 `unhandled_request_error` | `request_id`, `error_type`, `error_location`, 같은 시각의 요청 흐름 |
| `skn30-final-3team-dev-ai-terminal-failures` | `ai` | API·Worker의 `ai_terminal_failure` | `run_id` 또는 `request_id`, `failure_stage`, `failure_category`, `error_code`, `error_type` |

`source`는 `f2`, `f3` 같은 기능 문맥을 보여 주는 선택적 진단 필드다. 알람의 모듈 판정이나 로그
그룹 선택에는 사용하지 않으므로 새 AI 기능이 추가돼도 alarm name과 `module=ai` 계약은 유지된다.

### Backend 미처리 오류

다음 쿼리에서 Discord가 표시한 `request_id`를 추가해 동일 요청을 찾는다.

```text
fields @timestamp, request_id, status_code, error_code, error_type, error_location
| filter event = "unhandled_request_error"
| sort @timestamp desc
| limit 20
```

- `error_location`의 함수와 배포 revision을 먼저 확인한다.
- 같은 `request_id`의 access·도메인 로그에서 실패 직전 단계만 확인한다.
- 처리된 4xx나 F2의 분류된 502·503은 이 알람의 대상이 아니다.
- 상담 본문, 요청 body, 인증정보나 예외 메시지를 새 로그로 추가해 조사하지 않는다.

### AI 최종 실패

```text
fields @timestamp, source, request_id, run_id, status, status_code,
  failure_stage, attempt, failure_category, error_code, error_type,
  error_location, terminal_count
| filter event = "ai_terminal_failure"
| sort @timestamp desc
| limit 20
```

- `OUTPUT_CONTRACT`와 `PositionCardContractError`가 `CANDIDATE_CARDS`에서 발생하면 해당 `run_id`의
  단계 전이와 계약 검증 위치를 확인한다. 모델 원문·프롬프트를 Discord나 CloudWatch에 복사하지
  말고 재현 가능한 합성 입력과 구조화 출력 schema로 검증한다.
- `LEASE_EXPIRED_MAX_ATTEMPTS`·`failure_stage=EXECUTION`은 Worker가 최대 시도 초과 실행을 정리한
  신호다. `terminal_count`가 여러 실행을 집계할 수 있으며 현재 이 집계 이벤트에는 개별 `run_id`가
  없을 수 있다. 같은 시간대 Worker 로그와 durable `FAILED_TERMINAL` 상태를 함께 확인한다.
- 같은 시각에 계약 실패와 lease 종료가 각각 있으면 자동으로 하나의 원인으로 묶지 않는다.
  `run_id`, 단계와 발생 순서를 확인한 뒤 독립 장애인지 판단한다.

## 인프라 알람

RunPod 이외의 인프라 알람은 Logs Insights 자동 조회를 하지 않는다. `Alarm` 링크의 metric과 dimensions를
기준으로 ALB target health, ASG capacity 또는 RDS 자원을 확인한다. 애플리케이션 로그는 지표가
가리키는 시각과 서비스 상태를 확인한 뒤 필요한 경우에만 연다.

## RunPod 알람

RunPod 알람에는 외부 응답 본문이나 Secret을 붙이지 않는다. 다음 순서를 고정한다.

```text
just -f infra/justfile runpod-status
just -f infra/justfile runpod-reconcile
# 필요한 명시적 조정 명령을 검토·실행
just -f infra/justfile runpod-smoke
# CloudWatch Alarm의 OK 전이 확인
```

| 관측 상태 | 자동 변경 | 운영자 조치 |
|---|---|---|
| monitor error 또는 heartbeat 누락 | 없음 | Lambda log의 고정 outcome, EventBridge rule, Secret AWSCURRENT와 IAM을 확인한다. |
| RunPod API 2회 실패 | 없음 | `secret-status`, `runpod-status`로 세션과 read-only key를 확인하고 상태가 불명확하면 변경하지 않는다. |
| active endpoint, 공유 Pod 없음 | 없음 | `runpod-reconcile` 계획을 확인하고 실제 Pod 부재가 맞을 때만 `runpod-reconcile-apply`로 offline+refresh한다. |
| endpoint와 다른 Pod 또는 복수 Pod | 없음 | 어느 Pod도 삭제·선택하지 말고 Pod ID·Template ID와 최근 bootstrap generation을 대조한다. |
| SLLM/STT health 2회 실패 | 없음 | endpoint를 바꾸지 않고 인증 proxy·모델 기동 상태와 image digest를 확인한다. |
| offline orphan 60분 | 없음 | reconcile이 제시한 정확한 `runpod-delete <pod-id>`를 별도 검토·확인한다. |
| 연속 실행 8시간 초과 | 없음 | 진행 중 workload 담당자를 확인하고 종료 가능할 때 status와 정확한 Pod ID를 거쳐 삭제한다. |

조사 명령의 stdout, CloudWatch와 Discord에 API key, webhook, presigned URL, Secret Version hash나
외부 오류 본문을 복사하지 않는다. `runpod-reconcile`이 막힌 상태에서는 endpoint 또는 Pod를 Console에서
임의 수정하지 않는다.

## 상세 로그가 표시되지 않을 때

다음 경우에도 기본 alarm name·module·state·reason과 조사 링크는 전송된다.

- 20분 범위에 일치 로그가 없음
- Logs Insights 시작·조회 실패
- 조회 상태 대기가 2초를 넘음
- 안전 필드가 없는 결과만 반환됨

2초를 넘긴 실행 중 쿼리는 비용과 동시 실행 점유를 줄이기 위해 `StopQuery`를 best-effort로
호출한다. notifier 로그에는 AWS 예외 원문 대신 `QUERY_START_FAILED`, `QUERY_RESULT_FAILED`,
`QUERY_WAIT_TIMEOUT`, `QUERY_STOP_FAILED` 같은 고정 코드만 남는다. 이 오류는 Discord 기본 알림을
실패시키지 않는다.

## 알림 데이터 안전 경계

Discord 상세에는 조회와 출력 양쪽의 허용 목록을 통과한 다음 필드만 포함한다.

`@timestamp`, `source`, `request_id`, `run_id`, `status`, `status_code`, `failure_stage`, `attempt`,
`failure_category`, `error_code`, `error_type`, `error_location`, `terminal_count`

`@message`, `@ptr`, 예외 메시지, traceback, 음성·전사·상담 본문, 프롬프트, 모델 원문 응답과
인증정보는 조회 결과에 포함하지 않는다. 조사 중에도 이 경계를 완화하지 않는다.
