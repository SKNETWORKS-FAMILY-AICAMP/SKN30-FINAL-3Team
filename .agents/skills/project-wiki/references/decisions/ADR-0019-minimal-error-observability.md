---
status: 결정
updated: 2026-08-31
---

# ADR-0019: 개발 환경 오류 관측은 두 애플리케이션 신호와 기존 AWS 전달 경로로 한정한다

- 상태: 승인됨
- 결정일: 2026-08-31
- 승인 주체: 프로젝트 요청자
- 관련 계약: [오류 관측 계약](../contracts/observability.md), [API 계약](../contracts/api.md)
- Infra 세부 결정: [Infra ADR-0015](../../../infra/references/decisions/ADR-0015-cloudwatch-alarm-discord-delivery.md)

## 맥락

개발 환경에는 14일 CloudWatch 로그와 인프라 alarm이 있지만 예상하지 못한 Backend 500, F2의
분류된 AI 실패와 HTTP 200 상태 안에서 끝나는 F3 비동기 최종 실패를 사람이 식별할 수 없었다.
오류 envelope도 framework 404·405·422와 F2 Frontend 경로에서 일관되지 않았다.

초기 보완안은 공통 로그 스키마 전면 도입, 요청 완료·지연, AI 매 시도 비용, queue·heartbeat,
브라우저 telemetry와 여러 alarm을 한 번에 포함했다. 현재 1개 공유 dev 환경과 운영 인원을
고려하면 AWS 요금뿐 아니라 구현·튜닝·학습·당직 시간이 더 큰 비용이다.

## 결정

- 알람용 애플리케이션 이벤트는 예상하지 못한 Backend 500의 `unhandled_request_error`와 F2·F3
  최종 AI 실패의 `ai_terminal_failure` 두 개만 둔다.
- F3는 durable `FAILED_TERMINAL` 전이 뒤에만 알람 이벤트를 남긴다. 재시도, lease lost와
  superseded는 기존 진단 로그만 사용한다.
- 예외 원문과 전체 traceback 대신 예외 타입과 안전한 코드 위치만 남긴다.
- 공개 `/api/v1`의 framework 404·405·422를 공통 오류 envelope로 맞춘다. F2 화면은 공통
  `ApiError` 변환을 사용하고 원문이 아닌 기능 소유의 안전 문구와 요청 번호를 표시한다.
- React 최상위 Error Boundary는 복구 UI만 제공한다. 브라우저 오류 전송은 도입하지 않는다.
- 기존 CloudWatch·SNS·Discord를 사용하고 외부 관측성 제품은 도입하지 않는다. CloudWatch Alarm
  전달은 기존 delivery notifier를 수정하지 않고 별도 Lambda와 별도 webhook Secret으로 분리한다.

세부 필드, 발생·제외 조건과 알림 형식은 [오류 관측 계약](../contracts/observability.md)을 따른다.

## 결과

즉시 대응해야 하는 세 경로인 Backend 미처리 500, 동기 F2 최종 실패, 비동기 F3 최종 실패가
기존 AWS 운영면 안에서 Discord까지 연결된다. 기존 인프라 alarm도 이름·상태·사유를 사람이 읽을
수 있게 된다. 새로운 SaaS 요금과 계정·SDK 학습·데이터 정책 운영은 생기지 않는다.

반면 성공률, 지연, token 비용, queue 적체와 브라우저 오류를 자동 집계하지 않는다. 두 alarm의
오탐·누락과 수동 조사 시간을 운영 기록으로 남기고, 그 비용이 이 최소 구성을 넘을 때만 다음
관측 항목이나 외부 제품을 별도 결정한다.

F3의 DB commit과 로그 기록은 하나의 원자적 저장이 아니므로 그 사이 프로세스 종료 시 알람이
누락될 수 있다. 이를 없애는 DB outbox·재조정 작업은 이번 비용 범위에서 제외하며 exactly-once로
표현하지 않는다. 기존 `BaseException` 처리도 이번 변경에서 유지하므로 종료·취소 신호가 업무
실패로 오분류될 가능성은 후속 수명주기 변경에서 다룬다. OpenAPI path별 오류 응답 선언도 같은
이유로 후속 범위이며 이번에는 runtime envelope와 통합 테스트를 강제 경계로 사용한다.
