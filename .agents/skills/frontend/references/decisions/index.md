---
status: 결정
updated: 2026-08-26
---

# 프론트엔드 결정 인덱스

| ADR | 상태 | 요약 |
|---|---|---|
| [ADR-001](ADR-001-admin-dashboard-design-system.md) | 결정 | 관리자 대시보드 UI 기준으로 PatternFly 6과 AG Grid를 사용한다. |
| [ADR-002](ADR-002-typescript-standard.md) | 결정 | TypeScript와 strict 검사를 프론트엔드 표준으로 사용하고 기존 JavaScript는 점진적으로 전환한다. |
| [ADR-003](ADR-003-static-release-delivery.md) | 결정 | Vite 정적 artifact와 asset-first/index-last 복구 가능한 전달 |
| [ADR-004](ADR-004-shared-boundary.md) | 결정 | 여러 기능이 실제로 공유하는 전송·검증·표기 경계를 `src/shared`에 두고, 설정에 의존하는 모듈과 순수 모듈을 분리한다. |
| [ADR-005](ADR-005-feature-data-source.md) | 결정 | 데이터 출처를 기능 단위로 고르고, 지정하지 않으면 장부 출처를 따른다. |
