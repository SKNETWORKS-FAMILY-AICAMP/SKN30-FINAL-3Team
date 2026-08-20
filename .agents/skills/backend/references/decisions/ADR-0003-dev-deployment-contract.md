---
status: 결정
updated: 2026-08-20
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
- 전체 F3 handler가 구현되기 전 `WORKER_ENABLED=true`는 설정 오류로 시작을 거부한다.
- image는 비루트 사용자로 실행하고 비밀값을 포함하지 않는다.

## 결과

배포와 ASG 교체는 API와 Worker 프로세스를 항상 함께 준비할 수 있지만, Worker의 실제 F3 업무 처리는 후속 범위다. migration 실패는 새 application 시작을 차단하고 자동 down migration은 허용하지 않는다.
