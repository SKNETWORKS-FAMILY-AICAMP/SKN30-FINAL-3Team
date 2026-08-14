---
status: 결정
updated: 2026-08-14
---

# Accessibility

## 목표

WCAG 2.2 Level AA를 목표로 한다. PatternFly 또는 AG Grid 사용만으로 제품 접근성이 자동 보장된다고 가정하지 않는다.

- 일반 텍스트 대비: 최소 4.5:1
- 큰 텍스트 대비: 최소 3:1
- UI component와 의미 있는 graphic: 최소 3:1
- pointer target: 원칙적으로 최소 24x24 CSS px 또는 WCAG 2.2 spacing 예외 충족
- 색상만으로 상태를 전달하지 않는다.

## Keyboard & Focus

- 모든 기능은 키보드만으로 수행할 수 있어야 한다.
- Tab과 Shift+Tab은 컴포넌트 사이를 이동한다.
- Grid, Menu, Radio Group, Tabs와 Toolbar 같은 복합 위젯 내부는 PatternFly, AG Grid 및 WAI-ARIA APG의 방향키와 focus-management 패턴을 따른다.
- DOM 순서, 시각 순서와 focus 순서를 일치시킨다.
- 기본 focus outline을 제거하지 않고 PatternFly focus token을 사용한다.
- hover에서만 발견 가능한 action을 만들지 않는다.
- focus가 sticky header, modal 또는 toast에 가려지지 않게 한다.

## Semantics

- 실행은 button, 이동은 anchor를 사용한다.
- heading level은 문서 구조를 반영한다.
- main과 nav landmark를 사용하고 여러 navigation에는 구체적인 이름을 제공한다.
- label과 input을 연결하고 도움말과 오류는 aria-describedby로 연결한다.
- icon-only button에는 결과를 설명하는 accessible name을 제공한다.

## Modal

열 때 첫 의미 있는 요소로 focus를 이동하고 Tab은 Modal 안에서 순환한다. 일반 Modal은 Escape로 닫히며 닫힌 뒤 trigger로 focus를 복원한다. 배경 콘텐츠는 키보드와 보조기술에서 상호작용할 수 없어야 한다.

## Grid

- Grid container에 화면 맥락을 설명하는 이름을 제공한다.
- Grid에는 페이지 tab sequence의 진입점을 제공하고 내부 셀 이동은 공식 키보드 패턴을 따른다.
- cell renderer 안의 button, input 또는 menu 진입과 Grid navigation 복귀 방식을 검증한다.
- sort, filter, edit와 selection 결과를 screen reader가 인지할 수 있게 한다.
- screen reader 중요 화면은 pagination과 ensureDomOrder를 우선 검토한다.
- virtualisation 비활성화는 접근성과 성능을 실제 데이터로 함께 검증한 뒤 결정한다.

## Test Matrix

최소 다음을 확인한다.

- keyboard-only 전체 업무 수행
- 200% zoom과 browser text scaling
- prefers-reduced-motion
- high contrast 또는 forced colors 환경
- VoiceOver + Safari
- Windows screen reader 1종 + 지원 브라우저
- Grid sort, filter, edit, selection과 custom cell renderer announcement

지원 브라우저와 screen reader 조합이 확정되면 이 문서의 구체적인 테스트 매트릭스로 기록한다.

## 공식 참고

- [WCAG 2.2](https://www.w3.org/TR/WCAG22/)
- [WCAG target size minimum](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum)
- [WAI-ARIA Grid Pattern](https://www.w3.org/WAI/ARIA/apg/patterns/grid/)
- [WAI keyboard interface guidance](https://www.w3.org/WAI/ARIA/apg/practices/keyboard-interface/)
