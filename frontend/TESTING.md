# Frontend 검증

- `npm test` 또는 `npm run test:fast`: `tests/`의 `.test.ts`·`.test.mjs`를 자동 발견한다.
  브라우저 파일과 빌드 산출물이 필요한 `release-build.test.mjs`만 제외한다. 새 빠른 테스트는
  개별 npm 명령에 등록하지 않아도 기본 검증에 들어간다.
- `npm run test:browser`: `.browser.test.mjs` 파일을 자동 발견해 파일 단위로 직렬 실행한다.
  파일마다 설정이 다른 Vite를 시작하므로 같은 dependency cache에 대한 동시 최적화를 피한다.
  Playwright Chromium이 필요하며 모든 입력·응답은 합성 데이터다. 실제 AI 품질 평가를 대신하지 않는다.
- `npm run typecheck`, `npm run build`, `npm run test:release`: 타입과 정적 배포 산출물을 확인한다.
  릴리스 검사는 빌드한 뒤 실행한다.

개별 기능 명령은 빠른 작업용이다. 배포 검증에는 `test:fast`를 사용하고 브라우저 검사는 화면·훅·이동을
바꾸었을 때 함께 실행한다. 테스트 실패는 runner의 종료 코드로 상위 검증 단계에 전달된다.

합성 브라우저 회귀는 다음 저장 경계를 포함한다.

- 매물·구입장의 기존 상담 내용은 다른 필드 저장으로 다시 추가하지 않는다. 새 상담만 추가하고,
  서버 반영 후 조회가 실패한 경우 상세를 닫고 그리드의 `변경 저장`으로 복구할 때도 같은 상담을 다시 만들지 않는다.
  상세 안에서 실패 직후 재시도하면 이전 버전이 남을 수 있으므로 이 경로의 성공을 보장하는 검증은 아니다.
  저장 요청 중 추가로 입력한 값이 완료 응답에 덮일 수 있는 기존 상세 작성 상태 문제도 이번 범위에서 해결하지 않았다.
- F3가 열린 상세를 저장하면 패널을 닫고 명시적인 판정 버튼으로만 새 입력 버전을 실행한다.
  다른 경로로 열린 패널의 입력 버전이 바뀌면 이전 결과를 폐기 상태로 표시하고 명시적 재판정을 기다린다.
- 검색·그리드 필터 적용 후 실제 표시 행 수를 건수로 알린다.
- 캘린더는 월간 목록과 일정 편집 중 하나의 dialog만 활성화한다. 일정 편집을 닫으면 월간 목록으로 돌아간다.


F3 조회 복구는 `tests/f3-recovery.browser.test.mjs`의 합성 transport와 가상 시계로 60초 이후 지속·300초 조회 중단,
통신 오류, 기존 실행 404, result/status 순서 역전, 세션 종료 후 늦은 응답과 명시적 재판정을 검증한다.
실제 Windows Chrome 화면 검증은 headless 테스트와 구분한다. 2026-09-10 작업의 실행 범위·도구
연결 실패와 실제 모델 측정은 [F3 검증 보고서](../docs/validation/f3-reliability-performance-2026-09-10.md)에 기록한다.

후속 Linux Google Chrome 실제 창·100/200% 배율 검증은 `tests/manual/f3-linux-chrome.mjs`로
실행한다. 창 관리자의 실제 크기 제한과 좁은 확대 화면의 제목 가림은
[Linux Chrome 검증 기록](../docs/validation/f3-linux-chrome-2026-09-10.md)을 따른다.
`f3-panel.browser.test.mjs`는 매물·구입 패널을 Tab→Enter로 닫은 뒤 실행 버튼 초점 복원도 검사한다.
