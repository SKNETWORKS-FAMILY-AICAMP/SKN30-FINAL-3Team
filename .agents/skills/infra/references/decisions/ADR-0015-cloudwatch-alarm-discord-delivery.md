---
status: 결정
updated: 2026-09-01
---

# ADR-0015: CloudWatch Alarm은 전용 SNS·Lambda·Discord Secret으로 전달한다

- 상태: 부분 대체됨·코드 구현, AWS 미적용
- 결정일: 2026-08-31
- 승인 주체: 프로젝트 요청자
- 부분 대체: [ADR-0004](ADR-0004-dev-runtime-and-observability-baseline.md)의 SNS 사람 수신 구독 제외
- 관련 프로젝트 결정: [프로젝트 ADR-0019](../../../project-wiki/references/decisions/ADR-0019-minimal-error-observability.md)
- 대체 범위: webhook 값·Secret version의 `secrets.auto.tfvars`/Terraform 소유 방식은
  [ADR-0018](ADR-0018-runpod-bootstrap-secrets-monitoring.md)에서 대체한다.

## 맥락

기존 runtime SNS topic은 CodePipeline·CodeDeploy EventBridge 이벤트와 CloudWatch Alarm을 함께
받았고 기존 Discord Lambda는 alarm payload를 해석하지 않았다. alarm이 전송돼도 메시지는 어느
alarm이 어떤 상태로 바뀌었는지 알려 주지 못했다. 기존 delivery notifier는 이미 적용된 배포
경로이므로 alarm 지원을 덧붙이면 변경 위험과 두 payload 계약의 결합이 커진다.

## 결정

- 기존 runtime SNS topic, delivery notifier Lambda와 그 Discord Secret은 변경하지 않는다.
  EventBridge의 CodePipeline·CodeDeploy 알림은 계속 그 경로를 사용한다.
- CloudWatch Alarm 전용 SNS topic과 notifier Lambda를 만든다. 기존 인프라 alarm 6개와 새
  애플리케이션 alarm 2개는 `ALARM`·`OK` action을 전용 topic으로 보낸다.
- 새 Lambda는 표준 Alarm SNS payload에서 이름, 상태, 사유, 상태 전이 시각과 검증된 ARN을 읽어
  Discord에 보낸다. 모든 알람에 Alarm·장애 대응 Runbook 링크를 제공하고, 정확한 전체 이름으로
  매핑한 Backend·AI 애플리케이션 알람에는 미리 채운 Logs Insights 링크를 추가한다. SNS의 표시용
  `Region`이 아니라 account·alarm name과 일치하는 `AlarmArn`의 리전 코드를 Console URL에 쓴다.
- 애플리케이션 `ALARM`만 상태 전이 전후 10분을 Logs Insights로 조회해 허용된 안전 필드의 최근
  일치 1건을 “직접 원인으로 확정되지 않음”과 함께 표시한다. `source`는 선택적 기능 문맥이며
  라우팅은 `backend`·`ai` 모듈과 정확한 alarm name으로만 결정한다. `OK`와 기존 인프라 알람 6개는
  Logs API를 호출하지 않는다.
- 조회·polling·결과 렌더링은 모두 허용 목록을 적용하고 `@message`, `@ptr`, `GetLogRecord`를 사용하지
  않는다. 상태 대기는 최대 2초이며 실행 중이면 `StopQuery`를 best-effort로 호출한다. 조회 실패,
  시간 초과와 결과 없음은 고정 안전 코드만 남기고 기본 Discord 메시지는 성공 처리한다. Discord
  HTTP 실패만 예외로 반환해 SNS 재시도를 사용한다.
- 2,000자 상한과 mention 비활성화를 적용한다. 이름·모듈·상태·전이 시각, Alarm·해당 시
  Logs Insights·Runbook 링크, 제한된 사유, 안전 로그 순서로 보존하며 상세 로그부터 생략·축약한다.
  잘못된 payload는 비밀값을 읽거나 전송하지 않은 채 무시한다.
- notifier log group을 미리 만들고 14일 보존한다. 역할은 그 log group 쓰기와 전용 Secret 읽기만
  허용하던 기준에 API·Worker log group으로 제한한 `StartQuery`·`GetQueryResults`를 추가한다.
  resource-level 권한을 지원하지 않는 `StopQuery`만 별도 statement의 `Resource="*"`로 둔다. SNS
  topic policy는 같은 계정의 프로젝트 alarm publish만 허용한다.
- `alarm_discord_webhook_url`과 `alarm_discord_webhook_secret_version`을 기존 delivery 입력과
  별도로 둔다. 사람이 Discord에서 새 webhook을 만든 뒤 ignored `secrets.auto.tfvars`에 넣고,
  Terraform은 별도 Secrets Manager Secret의 write-only version으로 저장한다. 기존 webhook을
  복사하거나 재사용하지 않는다.
- Alarm Lambda와 구독은 새 Secret version 생성 뒤에 준비되게 해 최초 apply 중 비어 있는
  Secret을 읽는 경쟁을 막는다.
- 별도 KMS key, DLQ, DynamoDB 중복 제거와 외부 관측성 제품은 만들지 않는다.

## 결과와 적용 경계

배포 알림과 장애 알림은 서로의 parser·webhook·Secret·IAM을 공유하지 않는다. Alarm 메시지가
상태·이름·사유와 조사 진입점을 제공하고, 기존 notifier 회귀 위험도 피한다. 애플리케이션 ALARM
상태 전이당 20분 범위 쿼리 한 번만 추가하며 조회 실패가 중복 Discord 알림을 만들지 않는다.
추가되는 상시 운영 대상은 SNS topic,
Lambda, Secrets Manager Secret과 log group 하나씩, custom metric·alarm 두 개씩이다. SNS·Lambda는
오류 상태 전환 때만 호출하며 학습 대상은 기존 AWS 서비스 안에 머문다.

코드와 fixture 테스트만 이 결정에 포함한다. AWS 반영은 새 webhook URL 준비 후
`preflight → fmt/validate → saved plan 검토·승인 → apply → 실제 alarm fixture 검증 → drift` 순서로
별도 수행한다.
