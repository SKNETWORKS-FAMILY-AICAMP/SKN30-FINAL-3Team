---
status: 결정
updated: 2026-08-14
---

# Data Grid

## 선택 기준

AG Grid는 단순 조건 개수로 자동 선택하지 않는다. 다음을 함께 판단한다.

- 행과 열의 규모 및 가상화 필요
- 복합 정렬·필터, 열 재배치 또는 고정
- 셀 편집과 검증
- 행 선택과 대량 작업
- grouping, aggregation 또는 server-side row model
- 내보내기 요구
- 접근성, 모바일 업무와 라이선스 비용

단순 읽기 표는 PatternFly Table을 우선한다.

## Edition & License

- 기본은 AG Grid Community다.
- Enterprise 표시 기능은 라이선스와 비용 승인 후 사용한다.
- Row Grouping, Server-Side Row Model, Excel Export 등은 구현 시 설치 버전의 공식 기능표에서 edition을 확인한다.
- Community 대체안이 제품 요구를 충족하지 못할 때 Enterprise 도입을 별도 결정한다.
- 라이선스 키를 저장소, 브라우저 로그, 예시 또는 문서에 기록하지 않는다.

## Theme

신규 구현은 Quartz와 Theming API를 사용한다. theme는 하나의 productGridTheme에서 중앙 관리하고 PatternFly semantic token을 CSS 변수로 연결한다. 화면별 .ag-* override는 금지하며 필요한 예외는 wrapper scope, 사유와 검증을 기록한다.

기본 mapping 후보:

| AG Grid parameter | 제품 기준 |
|---|---|
| accentColor | --color-primary |
| textColor | --color-text |
| subtleTextColor | --color-text-subtle |
| borderColor | --color-border |
| invalidColor | --color-danger |
| headerTextColor | --color-text |
| wrapperBackgroundColor | --color-surface |
| headerBackgroundColor | PatternFly surface semantic token |

실제 parameter와 token 이름은 설치 버전에서 확인한다.

## Density & Columns

- 기본 fontSize 14px, rowHeight 약 40px, headerHeight 40~44px을 시작점으로 검증한다.
- compact mode는 데이터 전문 화면에서만 사용한다.
- WCAG target size와 인접 action 간격을 별도로 확보한다.
- 텍스트는 좌측, 숫자·금액·비율과 action은 우측 정렬한다.
- 숫자에는 tabular numbers를 사용한다.
- 중요 컬럼만 고정 폭을 주고 나머지는 flex와 minWidth를 우선한다.
- 긴 값은 truncation과 전체 값을 확인할 방법을 함께 제공한다.
- 상태는 강한 행 배경보다 label, icon과 text로 표현한다.
- hover와 selection을 명확히 구분한다.

## Toolbar & State

Grid 위에는 PatternFly Toolbar를 사용한다.

검색 → 필터 → 결과/선택 개수 → spacer → secondary action → primary action → overflow 순서를 기본으로 한다. Grid 안팎에 같은 검색·필터를 중복하지 않는다.

- Loading: 해당 영역 spinner 또는 skeleton과 설명
- No rows: 데이터 자체가 없음
- No matching rows: 필터 결과 없음과 필터 초기화
- Error: 원인 범위와 다시 시도
- Exporting: 진행 상태와 완료·실패 피드백

## Responsive

Grid를 자동 Card UI로 변환하지 않는다. 핵심 식별 컬럼을 먼저 보존하고 낮은 우선순위 컬럼은 숨길 수 있다. 가로 스크롤을 허용하되 좁은 화면에서 pinning이 데이터 영역을 침해하지 않게 한다. 반복 resize에서 sizeColumnsToFit을 호출하지 않고 flex와 minWidth를 우선한다.

모바일 업무가 데스크톱과 근본적으로 다르면 별도의 list/detail 패턴을 설계한다.

## Performance & Accessibility

row와 column virtualisation을 기본 유지하고 실제 데이터 규모로 scroll과 편집 성능을 측정한다. Screen reader가 핵심인 화면은 pagination, ensureDomOrder와 virtualisation 조정을 함께 검토한다. 접근성을 위해 virtualisation을 변경했다면 DOM 규모와 성능을 반드시 재검증한다.

custom cell renderer는 Grid navigation과 내부 action 진입·이탈을 모두 테스트한다. 정렬, 필터, 선택과 편집 결과가 시각적으로만 전달되지 않게 한다.

## 공식 참고

- [AG Grid Community and Enterprise features](https://www.ag-grid.com/javascript-data-grid/key-features/)
- [AG Grid Theming API](https://www.ag-grid.com/javascript-data-grid/styling-tutorial/)
- [AG Grid overlays](https://www.ag-grid.com/react-data-grid/overlays-overview/)
- [AG Grid accessibility](https://www.ag-grid.com/react-data-grid/accessibility/)
