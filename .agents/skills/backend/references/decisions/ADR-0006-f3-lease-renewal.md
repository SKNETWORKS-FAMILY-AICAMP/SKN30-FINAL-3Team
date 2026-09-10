---
status: 사용자 구현 승인·구현됨·팀 검토 전
updated: 2026-09-10
---

# ADR-0006: F3 단계 실행 중 lease 갱신

2026-09-10 사용자가 승인한 조회·판정 안정성 개선 계획을 구현한다. 기존 DB 작업·단일 Worker와
모델·후보 상위 5건을 유지한다. 프로젝트 ADR-0037에서 폐기한 자동 판정·완료 재사용·outbox를
복원하는 결정이 아니다.

## 결정

- 선점 lease 300초와 최대 선점 3회는 유지한다. 각 단계가 실행되는 동안 30초마다 갱신한다.
- heartbeat는 업무 세션과 다른 연결의 짧은 transaction을 사용한다. 원래 ORM 객체나 Session을
  스레드로 넘기지 않고 engine과 불변 실행 ID·사무소·소유자·시도 번호만 전달한다.
- DB `now()` 기준의 미만료 lease, 동일 소유자·시도·사무소, 실행 중 상태와 루트 실행을 모두
  확인한다. 만료·회수·완료·주차·release된 lease를 되살리지 않는다.
- 갱신 실패는 `LEASE_LOST`로 수렴한다. 대기 중 생성 task를 취소하고 후속 저장·단계를 막는다.
  기존 저장 직전 fencing도 유지하며, 서버의 terminal 실패나 새로운 상태로 바꾸지 않는다.
- 완료·예외·취소 때 heartbeat task와 진행 중 갱신을 회수한 뒤 다음 단계나 실패 처리를 한다.
  SQL lock timeout은 2초, statement timeout은 5초다. 연결 수립·pool 대기는 별도 DB 설정을 따른다.
- SIGTERM은 기존대로 현재 단계를 마친 뒤 종료한다. 프로세스 강제 종료 시에는 마지막 갱신 후
  lease가 만료되면 다른 Worker가 저장된 단계부터 회수한다.

## 대안과 영향

lease를 일괄 늘리는 방식은 장애 복구도 늦춘다. 모델 timeout·repair 예산을 줄이면 성공 가능성과
판정 품질에 영향을 준다. 독립 갱신으로 현재 실행 예산을 유지한다. 긴 단계에서는 DB 연결 하나와
30초당 짧은 UPDATE가 추가되며, Provider가 취소를 받더라도 이미 발생한 외부 과금까지 취소되는
것은 아니다. 동시 Worker 확장·우선순위·재시도 backoff는 이번 범위가 아니다.

## 검증

`backend/tests/unit/test_execution_lease.py`, `backend/tests/integration/test_execution_lease_db.py`에서
task 취소·정리, 실제 생성 대역 프로세스 강제 종료 후 회수, 별도 연결 commit, 만료·사무소·소유자·시도·종료 상태 fencing과 회수를 검사한다.
세부 실측과 Windows 검증 한계는 [검증 보고서](../../../../../docs/validation/f3-reliability-performance-2026-09-10.md)를 따른다.
