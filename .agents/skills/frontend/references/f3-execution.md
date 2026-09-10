---
status: 사용자 구현 승인·구현됨
updated: 2026-09-10
---

# F3 조회 재개와 재판정

`features/f3/hooks/useCrossJudgment.ts`가 실행 식별자와 polling을 소유하고 `CrossMatchPanel`은
그 상태를 표시한다. HTTP 응답 계약은 [API F3](../../project-wiki/references/contracts/api-f3.md)를 따른다.

- `resume()`은 캐시된 실행 ID가 있을 때 GET과 polling만 재개한다. 300초 `paused`와
  기존 실행의 통신 오류에는 ‘다시 확인’을 제공한다. 서버의 완료 결과를 조회하는 데 POST하지 않는다.
- `rerun()`은 현재 입력 버전을 명시적으로 승인하고 캐시를 지워 새 판정을 접수한다.
  최초 실행, 명시적 재판정, 404 복구와 입력 변경 후 재판정에 사용한다. 404를 자동 POST로 바꾸지 않는다.
- 결과 GET의 status가 직전 상태 GET보다 진행되었으면 결과 응답을 즉시 표시한다.
  terminal이면 추가 polling을 중단한다. 페이지 이동은 기존 실행 ID를 유지한다.
- 입력 버전이 바뀌면 명시적 재판정 전까지 `superseded`다. 패널 재열기는 같은 버전의
  메모리 캐시를 사용하며 이는 서버 완료 결과의 영구 재사용 정책이 아니다.
- effect의 취소·세대 번호와 세션 세대를 확인한 응답만 화면과 실행 캐시에 반영한다.
  `resetCrossJudgmentCache()`는 로그아웃 시 캐시를 비우고 세션 세대를 증가시킨다.
- PatternFly 컴포넌트와 기존 레이아웃은 유지한다. 상태별 버튼은 resume/rerun을 구분하며
  장부 편집·저장을 가로막는 완료 대기 모달을 만들지 않는다.

회귀는 `frontend/tests/f3-recovery.browser.test.mjs`와 기존 F3 panel/lifecycle 테스트를 따른다.
Windows Chrome에서 디자인·키보드·배율 검증이 필요한 변경이다. 실제 검증 상태와 재현 절차는
[2026-09-10 보고서](../../../../docs/validation/f3-reliability-performance-2026-09-10.md)에 기록한다.

명시적 패널 닫기는 패널을 연 버튼으로 키보드 초점을 복원한다. 저장·상세 닫기에는 이 복원을
적용하지 않는다. 매물 섹션 실행 버튼은 열 때 제거되므로 닫은 뒤 안정적인 ID로 다시 찾는다.
300초 정책과 실제 Linux Chrome 검증은 [후속 보고서](../../../../docs/validation/f3-linux-chrome-2026-09-10.md)를 따른다.
