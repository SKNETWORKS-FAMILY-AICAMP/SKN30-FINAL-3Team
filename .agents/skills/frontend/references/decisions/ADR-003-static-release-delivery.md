---
status: 결정
updated: 2026-08-24
---

# ADR-003: 개발환경 정적 release 전달

- 상태: 결정
- 결정일: 2026-08-20
- 상위 결정: [프로젝트 ADR-0011](../../../project-wiki/references/decisions/ADR-0011-dev-cicd-pipeline-modes.md)

## 결정

- Frontend는 runtime Docker image를 만들지 않고 Vite `frontend/dist/client` artifact를 배포한다.
- release build 전 clean install, TypeScript strict 검사와 현재 원장 변환 테스트를 필수로 통과한다.
- release test는 entry document와 hash가 포함된 JavaScript·CSS asset을 검증한다.
- manifest는 asset path, bytes, SHA-256, revision과 Pipeline execution ID를 기록한다.
- CloudFront Backend readiness를 확인한 뒤 asset-first/index-last 순서로 private S3에 배포한다.
- 기존 asset은 즉시 삭제하지 않고 이전 index와 manifest를 backup한다. 배포 또는 invalidation 실패 시 이전 index를 복원한다.
- Breaking API 변경은 독립 Frontend Pipeline으로 배포하지 않는다.
- 로컬 공개 설정은 tracked `.env.local`, 개인 override는 ignored `.env`, CI·배포 override는 process environment가 소유하며 이 순서로 우선한다.
- Vite profile env 파일은 사용하지 않고 Node env-file로만 dotenv를 로드한다.
- 브라우저 설정은 검증된 `VITE_` 키만 번들하고 API 기본 경로는 동일 origin의 `/api` 하위 상대 경로로 제한한다. 로컬 Backend proxy origin은 `FRONTEND_BACKEND_ORIGIN`으로 분리해 번들에서 제외한다.
