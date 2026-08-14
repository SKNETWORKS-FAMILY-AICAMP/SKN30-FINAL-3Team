---
status: 결정
updated: 2026-08-14
---

# Components & Content

## 공통 상태

모든 비동기 데이터 영역은 loading, empty, no-match, error와 success를 구분한다. 짧은 요청에 불필요한 full-page spinner를 쓰지 않고 해당 영역에서 상태를 표시한다. 긴 작업은 진행률 또는 현재 단계를 제공한다.

## Button

- PatternFly Button을 사용하고 실제 실행은 button, 이동은 link를 사용한다.
- 한 action cluster의 primary action은 원칙적으로 하나다.
- destructive action은 danger variant를 사용한다.
- icon-only action은 plain variant와 구체적인 accessible name을 제공한다.
- compact 크기는 Toolbar와 Grid action처럼 제약이 명확할 때만 사용한다.
- hover, active, focus, disabled와 loading 상태를 제공한다.
- loading 중 레이블과 버튼 폭이 불필요하게 흔들리지 않게 한다.

## Form & Input

- PatternFly Form, FormGroup, FormControl, TextInput과 HelperText를 우선한다.
- label은 명시하고 placeholder로 대체하지 않는다.
- 도움말과 오류는 입력과 aria-describedby로 연결한다.
- 오류 메시지는 무엇이 잘못됐고 어떻게 해결할 수 있는지 설명한다.
- 제출 실패 시 첫 오류 또는 error summary로 focus를 이동한다.
- disabled와 read-only를 구분하고 조회 데이터에는 DescriptionList도 검토한다.

## Card

서로 다른 정보 그룹을 구분할 때만 사용한다. 반복 행 데이터를 Card로 나열하거나 특별한 위계 없이 Card를 중첩하지 않는다. 전체 Card가 클릭 가능하면 내부 secondary action과 키보드 동작 충돌을 검증한다.

## Modal & Drawer

- 현재 흐름을 중단할 가치가 있는 작업에만 Modal을 사용한다.
- 단순 조회는 Drawer, Popover 또는 inline expansion을 우선 검토한다.
- Modal은 최대 90vw, 90vh이며 긴 본문만 scroll한다.
- 열 때 내부로 focus를 이동하고 닫을 때 trigger로 복원한다.
- Escape와 focus trap은 PatternFly 기본 동작을 유지한다.
- 데이터 손실 위험이 있으면 닫기 전에 확인한다.

## Alert & Toast

- Toast는 다음 행동이 필요 없는 완료 피드백에 사용한다.
- 중요한 오류와 영구 업무 상태는 페이지 내부 Alert에 표시한다.
- 오류에는 복구 방법 또는 다시 시도 액션을 제공한다.
- 사용자에게 전달해야 하는 Toast는 live region을 사용한다.
- 성공 Toast가 표시될 때 실제 화면 데이터도 함께 갱신한다.

## Navigation

PatternFly Page와 Navigation 구조를 사용하고 현재 위치를 명확히 표시한다. 이동과 실행 action을 혼용하지 않으며 각 navigation landmark에 이름을 제공한다. 3단계를 넘는 깊은 tree는 정보 구조를 재검토한다.

## Content & Iconography

- 짧고 구체적인 업무 용어를 제품 전체에서 일관되게 사용한다.
- 버튼은 저장, 사용자 추가, 다시 시도, CSV 내보내기처럼 동사 중심으로 작성한다.
- 확인, Yes/No, Click here처럼 결과가 불명확한 레이블을 피한다.
- 오류는 무엇이 실패했는가, 가능한 이유, 다음 행동 순서로 작성한다.
- 날짜와 숫자는 공통 formatter 및 Intl API를 사용한다.
- timezone, 단위, 천 단위와 소수 자릿수 기준을 명확히 표시한다.
- PatternFly icon set을 우선하고 같은 의미에 같은 아이콘을 사용한다.
- 아이콘만으로 의미가 불명확하면 텍스트 레이블을 제공한다.
