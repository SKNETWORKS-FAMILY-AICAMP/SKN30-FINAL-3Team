---
status: 결정
updated: 2026-08-14
owner: frontend
implementation: 계획됨
---

# Frontend Design Guide

관리자 대시보드의 제품 UI 정본이다. UI 작업자는 이 문서와 작업에 해당하는 세부 가이드를 구현 전에 확인한다. 이 결정은 main 병합 후 팀 공유 기준이 되며 implementation은 실제 코드와 의존성이 반영된 뒤 구현됨으로 변경한다.

## 기준과 정본

- 기준 스택: PatternFly 6 + AG Grid
- 설치 버전의 정본: frontend/package.json과 lockfile
- 선택 근거: [ADR-001](../decisions/ADR-001-admin-dashboard-design-system.md)
- 공식 기준: [PatternFly](https://www.patternfly.org/), [AG Grid](https://www.ag-grid.com/)

충돌 시 다음 순서로 판단한다.

1. 승인된 프로젝트 정책과 프론트엔드 ADR
2. 이 문서의 제품별 필수 규칙
3. 설치된 버전의 PatternFly semantic token과 React 컴포넌트 동작
4. 설치된 버전의 PatternFly 공식 접근성·디자인 가이드
5. 설치된 버전의 AG Grid Theming API·접근성·라이선스 가이드
6. PatternFly 6 Design Kit 기반의 승인된 제품 Figma

## 적용 범위

- 모든 인증 후 관리자 콘솔, 운영 도구, 백오피스와 데이터 관리 화면에 적용한다.
- PatternFly는 App shell, Navigation, Layout, Toolbar, Button, Form, Card, Modal, Alert와 Drawer를 담당한다.
- AG Grid는 정렬, 복합 필터, 선택, 편집, 대량 행 또는 가상화가 필요한 표형 UI에 한정한다.
- 단순 읽기 표는 PatternFly Table을 우선한다.
- 명시적으로 분리된 마케팅·브랜드 페이지는 별도 결정이 있을 때만 예외로 한다.

## Visual Theme & Atmosphere

- 신뢰할 수 있고 차분한 운영 도구를 지향한다.
- 장식보다 정보 구조, 정확한 상태, 단위, 숫자와 선택 범위를 우선한다.
- 정보 밀도는 높게 유지하되 위계, 정렬과 가독성을 희생하지 않는다.
- 일반 화면과 데이터 그리드는 같은 제품처럼 보여야 한다.
- 한 작업 영역의 primary action은 원칙적으로 하나만 둔다.

피해야 할 패턴:

- 과도한 glassmorphism, gradient, glow 또는 반복 애니메이션
- 모든 콘텐츠를 Card로 감싸는 구조
- 상태를 색상만으로 표현하는 방식
- 다른 디자인 시스템의 시각 언어 혼합
- 화면별 임의 Hex, spacing, radius, breakpoint 또는 .ag-* 패치

## 라이브러리 역할 경계

| 영역 | 기본 도구 | 필수 원칙 |
|---|---|---|
| App shell / Navigation | PatternFly | 기본 구조와 키보드 동작을 유지한다. |
| Button / Form / Modal / Alert | PatternFly | 직접 재구현하지 않는다. |
| Layout / Toolbar | PatternFly | 앱 전체 정렬과 간격 기준으로 사용한다. |
| Dense tabular data | AG Grid | 복잡한 표형 데이터에만 사용한다. |
| Grid 주변 필터와 액션 | PatternFly | Grid의 시각 언어가 앱 전체를 침범하지 않게 한다. |
| Grid header/cell/selection | AG Grid | 공통 Theming API로 PatternFly token에 맞춘다. |
| 단순 표 | PatternFly Table | AG Grid를 과도하게 사용하지 않는다. |

## 작업 전 필수 확인

1. 동일 목적의 PatternFly 또는 프로젝트 공통 컴포넌트가 있는가?
2. AG Grid가 필요한 데이터 규모와 조작 복잡도인가?
3. 사용하는 AG Grid 기능이 Community 범위인가?
4. loading, empty, no-match, error, disabled, read-only, permission-denied 상태가 정의됐는가?
5. 키보드만으로 전체 작업을 완료할 수 있는가?
6. 좁은 화면에서 핵심 정보와 액션의 우선순위가 정의됐는가?
7. 새 시각 값을 만들지 않고 semantic token으로 해결할 수 있는가?
8. 개인정보, 대량 작업, 내보내기 또는 파괴적 작업의 안전 규칙을 확인했는가?

## 세부 가이드

| 문서 | 읽는 조건 |
|---|---|
| [Tokens & Layout](tokens-and-layout.md) | 색상, 글꼴, 간격, 반응형, motion을 변경할 때 |
| [Components & Content](components-and-content.md) | 일반 컴포넌트, 상태 피드백 또는 문구를 구현할 때 |
| [Data Grid](data-grid.md) | 표 또는 AG Grid 화면을 구현할 때 |
| [Admin Safety](admin-safety.md) | 권한, 개인정보, 대량·파괴적 작업 또는 내보내기를 구현할 때 |
| [Accessibility](accessibility.md) | 모든 UI 작업. 복합 위젯이나 Grid 작업 시 전체를 읽는다. |
| [Review Checklist](review-checklist.md) | 구현 완료 후 자체 검토와 PR 작성 전에 |

## 예외와 변경

규칙을 벗어나는 PR에는 대상, 기존 규칙으로 해결할 수 없는 이유, 사용자 이점, 반응형·접근성·성능·라이선스 영향, 검증 결과와 향후 공통화 여부를 기록한다.

색상, typography scale, spacing, breakpoint, focus style, PatternFly wrapper, 공통 Grid theme 또는 density는 단일 화면에서 임의로 변경하지 않는다. 반복되는 실제 use case 또는 명확한 접근성 필요가 있을 때 공통 변경으로 검토한다.

라이브러리 업그레이드 시 migration/changelog, semantic token, 시각 회귀, Grid theme parameter, 키보드·screen-reader 동작과 라이선스 범위를 검증하고 이 문서의 updated 및 관련 세부 가이드를 함께 갱신한다.
