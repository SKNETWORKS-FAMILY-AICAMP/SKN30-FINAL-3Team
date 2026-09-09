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
- F3 목록·장부 상세 요약·결과 보기·새로고침은 실행을 접수하지 않는다. 원장 저장은 Backend 자동 판정 이벤트가 담당한다.
  이전 `useCrossJudgment` lifecycle fixture는 호환 훅의 외부 버전 갱신 회귀로 유지한다.
- `f3-panel.browser.test.mjs`는 GET 10회/실행 0건, 미판정 페이지, 편집값 유지, 관심없음 피드백, 권한 회수 시 본문 제거와 Drawer 초점 복귀를 검증한다.
  실제 `FAILED_TERMINAL` 종료 상태, polling 중 401, 목록/후보 `F3_CURSOR_INVALID`의 첫 페이지 복구도 포함한다.
  합성 transport 검증이므로 실제 API·DB·Worker 통합 검증을 대신하지 않는다.
- `f3-judgment-results.test.ts`는 미생성·공개 불가 건수 null 보존, API 계약 오류, URL 식별자 검증을 확인한다.
- 검색·그리드 필터 적용 후 실제 표시 행 수를 건수로 알린다.
- 캘린더는 월간 목록과 일정 편집 중 하나의 dialog만 활성화한다. 일정 편집을 닫으면 월간 목록으로 돌아간다.

실제 통합은 [F3 구현 기록](../docs/architecture/f3/implementation-and-validation.md)의 준비 절차 후
`F3_REAL_INTEGRATION=synthetic-local-validation F3_VALIDATION_DATABASE=f3_expansion_validation node tests/f3-real-integration.browser.mjs`로 실행한다. 기본 테스트에 포함하지 않는다. 로컬 5178·전용 합성 계정만 허용하며 API 응답을 대체하지 않는다. 사전 Worker 실행은 승인된 테스트 generator로만 모델 응답을 대체한다. 브라우저는 실제 피드백을 합성 DB에 기록하므로 검증 전용 DB에서만 실행한다.

기존 로컬 DB의 사전 적재 시드 결과는 별도로
`F3_SEED_INTEGRATION=existing-local-synthetic-seed F3_SEED_LOGIN_ID=f3_synthetic_dev node tests/f3-seed-integration.browser.mjs`
명령으로 확인한다. API를 기존 DB에 연결하고 시드 적재를 완료한 뒤 실행한다. `/auth/me`의 사무소 ID 2와
전용 로그인 ID를 검사하며 대상 ID는 실제 API 목록에서 찾는다. 개발 세션 생성 외에는 조회만 수행하고
매칭 실행·피드백 등 쓰기가 발생하면 실패한다. 시드 예시 배지, 양방향 결과, 후보 없음, 미판정과
10회 새로고침의 실행 접수 0건을 확인한다. 응답을 대체하지 않으며 기본 테스트에는 포함하지 않는다.
이 스크립트는 기존 격리 DB 통합 스크립트의 guard를 완화하거나 대체하지 않는다.
