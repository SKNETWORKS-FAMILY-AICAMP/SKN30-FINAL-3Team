---
status: 결정
updated: 2026-08-31
---

# 프론트엔드 결정 인덱스

| ADR | 상태 | 요약 |
|---|---|---|
| [ADR-001](ADR-001-admin-dashboard-design-system.md) | 결정 | 관리자 대시보드 UI 기준으로 PatternFly 6과 AG Grid를 사용한다. |
| [ADR-002](ADR-002-typescript-standard.md) | 결정 | TypeScript와 strict 검사를 프론트엔드 표준으로 사용하고 기존 JavaScript는 점진적으로 전환한다. |
| [ADR-003](ADR-003-static-release-delivery.md) | 결정 | Vite 정적 artifact와 asset-first/index-last 복구 가능한 전달 |
| [ADR-004](ADR-004-shared-boundary.md) | 결정 | 여러 기능이 실제로 공유하는 전송·검증·표기 경계를 `src/shared`에 두고, 설정에 의존하는 진입점과 순수한 진입점을 분리한다. 오류는 분류만 공유하고 사용자 문구는 각 기능이 소유한다. |
| [ADR-005](ADR-005-feature-data-source.md) | 결정 | 데이터 출처를 기능 단위로 고르고, 지정하지 않으면 장부 출처를 따른다. |
| [ADR-006](ADR-006-home-voice-intake.md) | 결정 | 첫 화면을 진입점 선택으로 두고, 신규 음성메모 접수가 상담 유형으로 장부를 판정한다. |
| [ADR-007](ADR-007-editable-fields-must-persist.md) | 결정 | 편집 가능하게 보이는 칸은 저장 경로가 있어야 한다. 없으면 편집을 열지 않고 이유를 밝힌다. |
