---
status: 결정
updated: 2026-08-14
---

# UI Review Checklist

작업과 관련된 항목만 사용하되 General과 Accessibility는 모든 UI 변경에서 확인한다.

## General

- [ ] 기존 PatternFly 또는 공통 컴포넌트를 우선 사용했다.
- [ ] 새 컴포넌트와 디자인 예외의 이유를 기록했다.
- [ ] semantic token만 사용하고 임의 Hex, spacing과 breakpoint를 추가하지 않았다.
- [ ] 좁은 화면부터 넓은 화면까지 업무 우선순위와 overflow를 확인했다.
- [ ] loading, empty, no-match, error, success와 permission-denied 상태를 구분했다.
- [ ] hover, focus, active, disabled, read-only와 loading 상태를 확인했다.
- [ ] 문구, 날짜, timezone, 숫자와 단위 표현이 일관된다.

## Accessibility

- [ ] 키보드만으로 전체 업무를 완료할 수 있다.
- [ ] 복합 위젯은 Tab 진입과 방향키 내부 탐색 규칙을 따른다.
- [ ] focus가 명확하고 가려지지 않으며 닫힌 overlay에서 trigger로 복원된다.
- [ ] 200% zoom, text scaling, target size와 색상 대비를 확인했다.
- [ ] 색상만으로 상태를 구분하지 않는다.
- [ ] icon-only action에 accessible name이 있다.
- [ ] Modal, Toast와 동적 결과의 screen-reader 전달을 확인했다.
- [ ] prefers-reduced-motion을 확인했다.

## Admin Safety

- [ ] 서버 권한 검증과 UI 권한 표현을 구분했다.
- [ ] 파괴적 작업에 대상, 영향과 복구 가능 여부를 표시했다.
- [ ] 대량 작업의 선택 건수와 적용 범위가 명확하다.
- [ ] 부분 실패와 안전한 재시도 방식을 정의했다.
- [ ] 개인정보 최소 노출, 마스킹, 복사와 내보내기 범위를 검토했다.
- [ ] 비밀값과 원문 개인정보를 오류, URL, Toast와 로그에 노출하지 않는다.

## PatternFly

- [ ] PatternFly 컴포넌트를 CSS로 불필요하게 재구현하지 않았다.
- [ ] 설치 버전에서 semantic token과 컴포넌트 API를 확인했다.
- [ ] Form helper와 error text 연결, Page와 Navigation landmark를 확인했다.
- [ ] 중요한 오류를 자동 소멸 Toast에만 의존하지 않는다.

## AG Grid

- [ ] AG Grid가 필요한 규모와 조작 복잡도인지 확인했다.
- [ ] 사용하는 기능의 Community/Enterprise 범위와 승인을 확인했다.
- [ ] 공통 productGridTheme와 Theming API를 사용했다.
- [ ] Grid 주변 control은 PatternFly를 사용했다.
- [ ] 컬럼 정렬, minWidth, flex, visibility와 좁은 화면 우선순위를 정의했다.
- [ ] No Rows, No Matching Rows, Loading, Error와 Exporting을 구분했다.
- [ ] Grid와 cell renderer의 키보드 진입·이탈을 확인했다.
- [ ] virtualisation 변경은 실제 데이터로 접근성과 성능을 검증했다.
- [ ] 화면별 .ag-* override와 반복 sizeColumnsToFit 호출을 추가하지 않았다.
