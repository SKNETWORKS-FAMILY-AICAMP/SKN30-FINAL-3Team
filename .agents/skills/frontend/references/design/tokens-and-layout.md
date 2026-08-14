---
status: 결정
updated: 2026-08-14
---

# Tokens & Layout

## Color

제품 토큰은 PatternFly semantic token의 alias로 정의한다. 컴포넌트에서 Hex를 직접 사용하지 않는다.

| Product token | PatternFly 기준 | 역할 |
|---|---|---|
| --color-primary | --pf-t--global--color--brand--default | 주요 행동과 선택 |
| --color-surface | --pf-t--global--background--color--primary--default | 기본 콘텐츠 배경 |
| --color-text | --pf-t--global--text--color--regular | 기본 텍스트 |
| --color-text-subtle | --pf-t--global--text--color--subtle | 보조 텍스트 |
| --color-border | --pf-t--global--border--color--default | 구분선 |
| --color-danger | --pf-t--global--color--status--danger--default | 오류와 위험 행동 |
| --color-success | --pf-t--global--color--status--success--default | 정상과 완료 |
| --color-warning | --pf-t--global--color--status--warning--default | 주의 |
| --color-focus | --pf-t--global--focus-ring--color--default | 키보드 focus |

실제 token 이름은 설치된 PatternFly 버전에서 검증한다. Palette token과 특정 Hex에 의존하지 않으며 상태는 색상과 아이콘 또는 텍스트를 함께 사용한다.

## Typography

PatternFly 기본 typography와 컴포넌트 스타일을 우선하고 화면별 크기를 만들지 않는다.

| 역할 | 기준 |
|---|---|
| H1 | Red Hat Display, 24px, 700, 1.3 |
| H2 | Red Hat Display, 20px, 700, 1.3 |
| H3 | Red Hat Display, 18px, 700, 1.3 |
| Body | Red Hat Text, 14px, 400, 1.5 |
| Help / Caption | Red Hat Text, 12px, 400, 1.5 |
| Code | Red Hat Mono, 14px, 400, 1.5 |

- HTML heading level은 문서 구조로 정하고 시각 크기 때문에 변경하지 않는다.
- 숫자, 금액과 시간 컬럼은 tabular numbers를 사용한다.
- 글꼴 로딩 실패 시에도 콘텐츠와 레이아웃을 사용할 수 있어야 한다.

## Spacing, Radius & Shadow

PatternFly semantic spacer가 있으면 global spacer보다 우선한다.

| Spacer | 기준 |
|---|---:|
| xs | 4px |
| sm | 8px |
| md | 16px |
| lg | 24px |
| xl | 32px |
| 2xl | 48px |
| 3xl | 64px |
| 4xl | 80px |

컴포넌트가 제공하는 radius와 shadow를 override하지 않는다. 임의 픽셀값은 1px 구분선, 데이터 밀도에 근거한 Grid dimension, 외부 이미지 고유 크기 또는 관련 이슈가 기록된 버그 회피에만 허용한다.

## Layout & Responsive

- 일반 페이지 최대 너비는 90rem을 상한으로 검토한다.
- Form과 상세 페이지는 읽기 편한 폭을 우선한다.
- Grid 중심 페이지는 가용 너비 100%를 사용할 수 있다.
- Grid를 Card와 이중 page inset으로 과도하게 감싸지 않는다.
- PatternFly 12-column Grid, Flex, Split, Stack과 Gallery를 우선한다.
- mobile first와 PatternFly breakpoint를 사용하고 화면별 breakpoint를 만들지 않는다.

| 구간 | 기준 |
|---|---|
| xs | 0 |
| sm | 36rem |
| md | 48rem |
| lg | 62rem |
| xl | 75rem |
| 2xl | 90.625rem |

페이지 inset은 md 미만 16px, md 이상 24px, xl 이상 32px을 기본으로 하되 PatternFly inset token을 우선한다.

좁은 화면에서는 페이지 제목과 primary action, 현재 상태와 KPI, 검색·필터, 핵심 데이터, 보조 메타데이터, 저빈도 작업 순서로 보존한다. Sidebar는 overlay/collapsed, Form은 한 열, 저빈도 액션은 overflow로 전환한다.

## Motion

PatternFly motion token을 사용한다.

- 작은 상태 변화: 50~100ms
- hover와 button feedback: 100~200ms
- fade와 alert: 약 200ms
- expand/collapse: 200~300ms
- panel과 drawer: 300~400ms
- 500ms 이상: 명확한 이유가 있을 때만

prefers-reduced-motion을 존중하고 slide, scale, jiggle과 데이터 행 애니메이션은 fade 또는 즉시 전환으로 축소한다. 대량 데이터 갱신, 정렬과 필터 결과에 장식적 행 애니메이션을 사용하지 않는다.

## 공식 참고

- [PatternFly design tokens for development](https://www.patternfly.org/foundations-and-styles/design-tokens/develop/)
- [PatternFly spacers](https://www.patternfly.org/foundations-and-styles/spacers/)
- [PatternFly 6 upgrade guide](https://www.patternfly.org/get-started/upgrade/)
