---
status: 구현됨
updated: 2026-09-09
---

# 공유 dev 모델 대상 선택

운영 진입점은 [개발자 인프라 운영](../../../../infra/operations/README.md)의 `dev-start`다.
Backend의 `src/model_selection.py`가 DB 조회·검증·트랜잭션을 소유하며 Infra는 maintenance
호스트에서 배포된 CLI를 실행한다. 별도 HTTP API나 Infra의 직접 SQL 쓰기를 추가하지 않는다.

## CLI 계약

- 기존 `--brokerage-id ID --capability CAPABILITY` 단일 대상 입력을 유지한다.
- `--list-targets --provider PROVIDER --model MODEL --shared-dev`는 중개사 ID와 capability별
  현재 활성 설정·호환 여부·대기/실행 요청 수, 원하는 설정, 검토 snapshot 해시를 반환한다.
  사무소 연락처·고객 데이터·DB URL·비밀값은 반환하지 않는다.
- `--apply --workloads-stopped --expected-snapshot HASH --target ID:CAPABILITY`를 반복하여
  확인한 대상만 한 트랜잭션으로 변경한다. provider/model도 목록 조회와 같은 값으로 전달한다.
  빈 대상 목록은 남은 호환성과 snapshot 확인만 수행한다.
- `Capability`의 허용값은 `POSITION_CARD`, `BROKERAGE_JUDGMENT`, `CHATBOT`이다.
  provider/model은 AI의 기존 `ProviderKind`·`GeneralModel` 조합 검증을 사용한다.
- 목록 조회·배치 적용은 명시 모델을 사용하며 AI endpoint 초기화나 추론을 수행하지 않는다.
  따라서 RDS·maintenance 호스트만 준비되고 GPU endpoint는 offline인 시점에 조회할 수 있다.

## 트랜잭션과 기동 경계

호출자가 API·Worker 중지를 확인한다. 단일·배치 적용은 같은 helper에서 `brokerage → ai_model_config →
agent_run → chat_request` 순서로 `EXCLUSIVE` table lock을 획득한다. 그 뒤 배치 적용이 활성 설정과
대기 요청 snapshot을 다시 조회하며 transaction commit/rollback까지 보호한다. 행 잠금 관례를
따르지 않는 직접 UPDATE·INSERT나 SELECT FOR UPDATE도 이 구간에는 대기한다. 일반 SELECT는 허용한다.
검토 후 변경, 존재하지 않는 대상, 대기/실행 요청, 선택하지 않은 비호환 활성 설정은 쓰기 전에 거부한다.

이 잠금은 중지된 maintenance 작업 전용이다. `SET LOCAL lock_timeout='5s'`,
`statement_timeout='30s'`로 대기와 개별 SQL 실행을 제한하며 lock timeout·deadlock·검증 오류는
전체 트랜잭션을 rollback한다. 사용자 확인·GPU 준비·외부 네트워크 호출을 잠금 안에서 실행하지 않는다.
`EXCLUSIVE`는 단일 경로의 brokerage 행 잠금이 먼저 잡힌 상태에서 다른 테이블 잠금과 역전되는 것을
피하도록 공통 helper에서 가장 먼저 사용한다. 신규 요청·DML을 기동 직전까지 영구 차단하는 잠금이
아니므로 commit 후에도 API·Worker 중지 및 운영자 순차 실행 계약을 유지해야 한다.
잠금 충돌 기준은 [PostgreSQL 15 table locks](https://www.postgresql.org/docs/15/explicit-locking.html#LOCKING-TABLES)를 따른다.

선택한 설정이 같으면 버전을 추가하지 않는다. 변경한 대상은 이전 설정을 비활성화하고
새 버전을 삽입하며 기존 설정·run snapshot을 삭제하거나 덮지 않는다. 여러 활성 설정이
남은 과거 데이터도 모두 조회하여 비호환 설정을 숨기지 않는다.

유지보수 CLI가 없는 호스트·구 Backend 이미지는 배포 선행 조건을 반환한다. Infra가 이전 검증
revision을 복원할 수 없으면 최초 `app-deploy` 절차가 필요하다.
CLI가 그 명령을 대신 실행하거나 API·Worker를 시작하지 않는다. 모델 준비 확인 후 적용하고,
기동 전 호환성을 다시 확인하는 순서는 Infra가 소유한다. 클라우드 전환만으로 모델이 같으면
DB 버전은 그대로 유지된다.

검증은 `backend/tests/unit/test_model_targets.py`와
`backend/tests/integration/test_model_targets_postgres.py`,
`backend/tests/integration/test_model_targets_concurrency.py`에 둔다. 통합 검사는 일회성
PostgreSQL의 격리 schema에서 migration부터 실행하며 공유 dev DB를 사용하지 않는다.
