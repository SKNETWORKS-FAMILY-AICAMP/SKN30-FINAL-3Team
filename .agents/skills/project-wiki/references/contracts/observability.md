---
status: 결정
updated: 2026-08-31
---

# 오류 관측 계약

이 문서는 개발 환경에서 **사람이 즉시 확인해야 하는 오류 신호**와 모듈 간 전달 경계를 정한다.
전체 로그를 하나의 새 스키마로 이관하거나 외부 관측성 제품을 도입하는 계약은 아니다.

## 공통 안전 규칙

- 음성, 전사, 상담 본문, 프롬프트, 모델 원문 응답, 인증정보, Discord webhook과 예외 메시지는
  로그·metric·알림에 기록하지 않는다.
- API 요청 로그는 기존 `request_id`를 사용하고 F3 최종 실패는 내부 `run_id`를 상관키로 사용한다.
  외부 `X-Request-ID`는 canonical UUID 모양만 받아들이고 나머지는 서버 UUID로 교체해 임의 원문이나
  과도한 문자열이 로그 상관키가 되지 않게 한다.
- 예외 진단은 `error_type`과 `module:function:line` 형식의 `error_location`까지만 허용한다. 전체
  traceback, 소스 경로와 지역 변수는 남기지 않는다.
- CloudWatch Alarm을 만드는 이벤트 이름은 아래 두 개뿐이다. 기존 업무 로그를 전부 새 공통
  스키마로 바꾸지 않는다.

## 알람 이벤트

| event | 발생 조건 | 필수 안전 필드 | 발생하지 않는 조건 |
|---|---|---|---|
| `unhandled_request_error` | Backend가 예상하지 못한 예외를 공개 500으로 변환함 | `component=backend`, `status_code=500`, `error_code`, `error_type`, `error_location`, API `request_id` | 처리된 4xx, F2의 분류된 502·503 |
| `ai_terminal_failure` | F2가 502·503으로 끝나거나 F3가 `FAILED_TERMINAL`을 durable commit함 | `component=ai`, `source=f2\|f3`, 상태 또는 상태 코드, 안전한 실패 분류, 상관키 | F3 재시도, lease lost, superseded, 아직 commit되지 않은 실패 |

최대 시도 초과 실행을 한 트랜잭션에서 여러 건 정리하면 이벤트 한 건에 `terminal_count`를
기록한다. 알람은 정확한 업무 건수 계산이 아니라 장애 존재 탐지가 목적이다.

F3 이벤트는 DB 종료 상태 commit 뒤 한 번 기록을 **시도하는 best-effort 신호**다. commit과 로그
사이에서 프로세스가 죽으면 durable `FAILED_TERMINAL` 상태는 남지만 이벤트는 누락될 수 있다.
현재 범위는 DB outbox나 주기적 재조정 작업을 추가하지 않으므로 exactly-once 전달을 보장하지 않는다.

## HTTP 오류와 Frontend 경계

- `/api/v1`의 애플리케이션 오류와 framework 404·405·422는 모두
  `{code, message, request_id}`를 반환한다. health 경로는 이 공개 API envelope의 대상이 아니다.
- Frontend 공통 응답 변환기는 `status`, `code`, `request_id`를 `ApiError`에 보존한다. 계약에 없는
  4xx는 5xx 재시도 오류가 아니라 `contract`로 분류한다.
- F2는 multipart 전송을 기능 내부에 유지하되 같은 공통 오류 변환기를 사용한다. 화면 문구는
  `kind`와 허용된 `code`로만 선택하고 서버 `message`를 그대로 표시하지 않는다. `request_id`가
  있으면 안전한 사용자 문구에 요청 번호로 덧붙인다.
- 최상위 React Error Boundary는 빈 화면 대신 새로고침 가능한 안전 화면을 보여 준다. 브라우저
  오류를 서버나 외부 서비스로 전송하지 않는다.

| HTTP | Backend 공개 조건 | Frontend 공통 분류 |
|---|---|---|
| 401 | 세션 없음·만료 | `unauthorized` |
| 403 | 권한 부족·CSRF 불일치 | `forbidden` |
| 404 | route·대상 없음, tenant 은닉 | `notFound` |
| 405 | 허용되지 않은 method | `contract` |
| 409 | 낙관적 잠금 등 상태 충돌 | `conflict` |
| 400·422 | 요청·도메인 검증 실패 | `validation` |
| 그 밖의 4xx | 현재 명시 계약 없음 | `contract` |
| 500·502·503 | Backend 예상 밖 오류·F2 처리/가용성 실패 | `server` |

이 표는 공통 분류 계약이며 모든 화면에 전역 재로그인·재시도 동작이 구현됐다는 뜻은 아니다.
현재 이 변경에서 사용자 문구까지 강제하는 기능은 F2다.

## CloudWatch와 Discord 경계

- API log group의 `unhandled_request_error`, API·Worker log group의 `ai_terminal_failure`를
  dimension 없는 custom metric으로 변환한다. 일치 이벤트가 없을 때 0 datapoint를 계속 발행하지
  않는다. 각 alarm은 5분 합계가 1 이상이면 `ALARM`, 데이터가 없으면 정상으로 본다.
- 기존 인프라 alarm 6개와 위 애플리케이션 alarm 2개는 Alarm 전용 SNS topic으로 `ALARM`·`OK`
  상태만 전송한다. `INSUFFICIENT_DATA`는 전송하지 않는다.
- Alarm 전용 Lambda는 기존 CodePipeline·CodeDeploy notifier와 분리한다. Discord 메시지는
  `AlarmName`, `NewStateValue`, `NewStateReason`만 포함하고 2,000자 이하로 자르며 mention parsing을
  끈다. 잘못된 fixture는 무시하고 Discord HTTP 실패는 SNS 재시도를 위해 실패로 반환한다.
- Alarm notifier는 기존 delivery webhook을 재사용하지 않는다. 새 Discord webhook URL을 별도
  ephemeral Terraform 입력으로 받아 독립 Secrets Manager Secret/version으로 저장한다.

## 이번 범위에서 제외

- Better Stack·Sentry·OpenTelemetry 등 외부 관측성 제품
- 브라우저 runtime telemetry와 사용자 입력 수집
- 전역 access log 스키마 이관, tracing, dashboard
- Provider 시도별 token·비용·latency, queue age, Worker heartbeat와 알람
- DLQ, 별도 KMS key, 중복 제거 저장소
- DB outbox를 통한 최종 실패 알림의 exactly-once 전달
- F3의 기존 `BaseException` 업무 실패 경계 변경. 종료·취소 신호 오분류 가능성은 잔여 위험이다.
- 상태별 `ErrorResponse`를 모든 OpenAPI path operation에 반복 선언하는 작업. runtime envelope와
  통합 테스트를 이번 강제 경계로 사용한다.

이 제외 항목은 장애 빈도와 운영 시간이 실제로 증가했을 때 측정 근거와 함께 다시 검토한다.
