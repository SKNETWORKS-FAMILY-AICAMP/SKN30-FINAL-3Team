---
status: 결정
date: 2026-09-04
implementation: 구현됨
---

# ADR-008: 캘린더 월간 뷰는 PatternFly `CalendarMonth`가 아니라 직접 만든 그리드를 쓴다

## 맥락

캘린더 화면(F4-CAL)은 한 날짜 칸에 여러 일정(장부 읽기 전용 항목 + 사용자가 만든 편집 가능한
일정)을 함께 얹어야 한다. PatternFly 6에는 `CalendarMonth`가 있지만 실제로는 날짜 하나를 고르는
date-picker다 — `onChange`가 선택한 날짜 하나만 돌려주고, `dayFormat`으로 칸 내용을 약간
바꿀 수는 있어도 한 칸에 여러 항목을 리스트로 얹거나 항목마다 클릭 핸들러를 다는 구조는 아니다.
이 저장소에는 다른 달력 라이브러리가 없다(`frontend/package.json` 확인).

디자인 가이드(`.agents/skills/frontend/references/design/index.md`)는 PatternFly 기본
컴포넌트에서 벗어나면 대상·이유·사용자 이점과 접근성·성능 영향을 문서화하도록 요구한다.

## 결정

캘린더 월간 그리드는 `CalendarMonth`를 감싸 쓰지 않고, 네이티브 `Date`로 날짜를 계산해
(`frontend/src/features/calendar/model/monthGrid.ts`) PatternFly `Grid`가 아니라 일반
`<div>`/CSS Grid로 직접 그린다.

- 이유: `CalendarMonth`의 커스터마이즈 표면(`dayFormat`, `cellAriaLabel`)은 날짜 하나당
  항목 여러 개를 그리기에 좁다. 감싸 쓰면 라이브러리의 내부 렌더링 가정과 계속 씨름하게 된다.
- 사용자 이점: 하루에 여러 일정(장부 항목 + 캘린더 일정)을 동시에 보고, 캘린더 일정만 클릭해
  바로 수정할 수 있다.
- 접근성: 날짜 칸의 "+" 버튼과 각 일정 항목(편집 가능한 것)은 실제 `<button>`이라 표준 tab
  순서와 키보드 활성화를 그대로 받는다. `role="grid"` 같은 전체 ARIA grid 패턴(로빙
  tabindex 등)은 넣지 않았다 — 각 칸이 이미 네이티브 포커스 가능 요소로만 이루어져 있어
  추가 복잡도 없이 키보드로 완결된다.
- 성능: 새 의존성이 없으므로 번들 비용이 없다.

## 결과

- 새 npm 의존성이 없다.
- 월 이동, 오늘 강조, 요일 헤더 같은 달력 고유 동작을 직접 구현해야 했다
  (`frontend/src/features/calendar/model/monthGrid.ts`의 `monthGridDays`·`addMonths` 등).
- `ADR-005`가 "세 번째 데이터 출처 기능이 생기면 값 추가 방식을 다시 본다"고 남겨 둔 지점에
  캘린더가 도달했다(`VITE_CALENDAR_SOURCE`가 세 번째 기능별 출처 값). 이번에는 같은 패턴을
  그대로 재사용했고, 값 목록 방식으로 바꿀지는 아직 다시 보지 않았다.

## 고려한 대안

- **`CalendarMonth`를 `dayFormat`으로 확장**: 날짜 칸에 커스텀 노드를 넣을 수는 있지만, 항목별
  클릭 핸들러와 "이 칸에 몇 개까지 보여줄지" 같은 레이아웃 제어권이 라이브러리 쪽에 있어
  일정이 늘어날수록 감싸는 코드가 라이브러리 내부를 추정해야 하는 상황이 반복될 것으로 판단했다.
- **새 달력 라이브러리 도입**: 번들 비용과 라이선스·유지보수 상태 검토가 새로 필요하고, PatternFly
  6과 시각 언어를 맞추는 작업이 추가된다. 이번 범위(월간 그리드 하나)에 비해 크다.
