---
status: 결정
updated: 2026-08-24
---

# ADR-0003: 개발환경 Backend·Worker 배포 계약

- 상태: 승인됨
- 결정일: 2026-08-20
- 상위 결정: [프로젝트 ADR-0011](../../../project-wiki/references/decisions/ADR-0011-dev-cicd-pipeline-modes.md)

## 결정

- API와 Worker는 Backend와 `brokerage-ai`를 lockfile 기반 non-editable 설치한 같은 immutable image digest를 사용한다.
- API·Worker runtime에는 `DB_URL`만 필요하고 `DB_MIGRATION_URL`은 선택값이다. 전진 migration one-shot에서만 migration URL을 필수 검증한다.
- migration은 PostgreSQL advisory lock을 획득한 뒤 Yoyo를 실행한다.
- runtime·migration DB 연결은 RDS CA `verify-full`을 사용한다. root 전용 host config directory는 컨테이너에 노출하지 않고 공개 CA bundle 파일만 read-only로 mount한다.
- ALB private-IP Host는 live/readiness endpoint에서만 허용한다. 일반 API는 기존 TrustedHost allowlist를 유지한다.
- Worker는 `WORKER_ENABLED=false`에서 DB readiness, health와 graceful shutdown을 제공하고 작업을 claim하지 않는다.
- F3 handler 구현 뒤 `WORKER_ENABLED=true`는 DB와 LLM Provider 설정을 기동 전에 검증하고 RDS
  polling을 시작한다. Provider나 모델 기본값은 코드에 두지 않고 사무소별 활성
  `ai_model_config`에서 선택한다.
- 현재 Worker 조립은 ADR-0014의 합성 프로토타입만 명시적으로 허용한다. 실제 배포 설정의
  `WORKER_ENABLED`와 `F3_ALLOW_SYNTHETIC_PROTOTYPE` 기본값은 모두 `false`다. 활성 Worker는
  검토된 합성 전용 데이터셋에서 두 값을 모두 `true`로 명시해야 하며, 합성 opt-in이 없으면 DB
  readiness·Provider 초기화·작업 선점 전에 기동을 거절한다. 운영 Provider 선택과 실데이터
  마스킹 전환을 이 결정으로 승인하지 않는다.
- 정지 신호를 받으면 현재 application 단계까지 마친 뒤 다음 실행을 claim하지 않는다. Worker
  프로세스 수명 동안 하나의 asyncio loop를 재사용한다.
- image는 비루트 사용자로 실행하고 비밀값을 포함하지 않는다.

## 결과

배포와 ASG 교체는 API와 Worker 프로세스를 항상 함께 준비한다. 비활성 모드는 기존 운영 계약을
유지하고, 활성 모드는 저장된 상태·lease를 정본으로 F3 단계를 실행한다. migration 실패는 새
application 시작을 차단하고 자동 down migration은 허용하지 않는다.
