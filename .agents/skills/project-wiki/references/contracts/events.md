---
status: 계획됨
updated: 2026-08-12
---

# 이벤트 계약 규칙

구체적인 이벤트는 기능 기획이 승인될 때 추가한다.

## 최소 봉투 후보

| 필드 | 의미 |
|---|---|
| `event_id` | 이벤트 중복 판별 식별자 |
| `event_type` | 이벤트 종류와 버전 |
| `occurred_at` | 발생 시각 |
| `trace_id` | 서비스 간 추적 식별자 |
| `producer` | 생성 모듈 |
| `payload` | 이벤트별 데이터 |

## 기본 규칙

- 이벤트 계약은 Pydantic 및 JSON Schema처럼 독립적인 형식으로 정의한다.
- SQLModel 테이블 클래스를 이벤트 계약으로 직접 사용하지 않는다.
- 소비자는 중복 전달을 허용하고 멱등하게 처리한다.
- 재시도 가능 오류와 영구 오류를 구분한다.
- 큰 데이터나 파일 자체를 큐에 넣지 않고 참조와 무결성 정보를 전달한다.
- 개인정보는 꼭 필요한 필드만 포함하고 보존·삭제 정책을 명시한다.
- 에이전트 작업은 필요하면 `run_id` 또는 `thread_id`를 전달한다.

## F3 내부 변경 outbox — 2026-09-09 구현

[ADR-0035](../decisions/ADR-0035-f3-conditional-automation-results.md)에 따라 F1 원천 변경과 같은 PostgreSQL transaction에서 `match_source_revision`과 `match_change_outbox`를 갱신한다. 기록 실패는 F1 저장도 rollback한다.

내부 outbox는 사무소당 한 행에 `brokerage_id`, `revision`, `source_table`, `source_id`, `changed_at`만 병합한다. 위 일반 메시지 봉투 후보를 채택한 외부 큐 이벤트가 아니다. 상담 원문·연락처·prompt·변경 전후 전문은 넣지 않는다.

Worker는 원천 상태로 영향 대상을 재구성하고 대상별 desired revision/due_at을 저장한 transaction에서 소비 행을 제거한다. 재처리는 revision·입력 identity와 기존 실행 재사용으로 멱등하게 처리하며 역참조에 없던 새 후보도 포함하도록 사무소 양쪽 장부를 보수적으로 검증한다. 모델 작업 실패·재시도는 `agent_run`이 소유하고 outbox가 추론 완료를 기다리지 않는다.

SQS·DLQ 전환은 후속이며 현재 외부 이벤트 전달 보장은 제공하지 않는다. 구체적인 상태와 복구는 [구현 기록](../../../../../docs/architecture/f3/implementation-and-validation.md)을 따른다.

`match_change_outbox.brokerage_id`는 PK다. `LIMIT`은 사무소 병합 행 개수의 상한이며
사무소 내 개별 변경 이벤트 개수가 아니다. 소비자는 `FOR UPDATE SKIP LOCKED`로 선택한
행을 transaction 종료까지 잠그고 해당 사무소·revision만 삭제한다. 같은 사무소의 동시
upsert는 이 잠금을 기다리므로 소비 후 커밋되는 변경은 새 outbox로 남는다.
