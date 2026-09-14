# F3 Linux Chrome 검증 및 300초 조회 상한 — 2026-09-10

후속 사용자 요청에 따라 **설치된 Linux Google Chrome 148.0.7778.215의 실제 창**에서
수정본을 확인했다. Headless Chromium 결과와 구분한다. 자동 조회 상한을 **60초 → 300초**로
늘렸으며 명시적 패널 닫기 후 실행 버튼으로 키보드 초점을 복원했다.

기존 [F3 성능 보고서](f3-reliability-performance-2026-09-10.md)의 Backend·모델 실측은 그대로
유효하다. 이번 추가 변경은 Frontend와 검증·문서에 한정한다. Windows Chrome은 실행하지 않았다.

## 검증 환경과 결과

- 작업 브랜치 `fix/f3-reliability-performance`, 워크트리 `/tmp/SKN30-FINAL-3Team-f3-performance`.
- 수정본 `http://localhost:5183/`, 이전 `dev` 화면 `http://localhost:5184/`.
- 실제 API 8013·별도 Worker·합성 전용 DB `f3live`를 사용했다. 기존 5173 서비스와 개인 데이터는 변경하지 않았다.
- 전후 화면 비교와 장시간·장애 시나리오는 실제 제품 화면에 결정적인 F3 transport 대역을 주입했다.
  장부는 합성 DB에서 읽고, 편집 가능 여부는 입력 후 원래 값으로 되돌려 확인했다. 실제 모델 검증은 별도로 수행했다.
- Chrome `chrome://settings/appearance`의 페이지 배율을 실제로 변경했다. 100%의 devicePixelRatio=1,
  200%=2를 확인했다. viewport 축소·핀치 확대를 200%로 간주하지 않았다.
- 창 크기 요청은 1920×1080과 1366×768이다. WSL 창 관리자가 전자를 **1919×1079**로 제한했다.
  후자는 정확히 1366×768이다. Chrome 도구 모음을 뺀 내용 영역은 각각 1919×940, 1366×629이며
  200%에서는 CSS viewport가 959×470, 683×314였다. 정확한 1920×1080 창으로 통과했다고 주장하지 않는다.
- 200%에서 Playwright의 기본 캡처가 절반 영역만 담는 현상을 확인해, 최종 이미지는 Chrome의
  `Page.captureScreenshot` 직접 캡처로 기록했다.

| 검증 | 결과 |
|---|---|
| 매물·구입 × 창 크기 2종 × 100/200%, 총 8조합 | 같은 합성 결과의 패널 폭·주요 font/color/background/padding/gap/radius 일치 |
| 페이지 다음/이전, 패널 닫기·재열기 | 8조합에서 버튼 초점·화면 내 표시·가림 없음, 실행 접수 1회 유지 |
| 명시적 패널 닫기의 초점 복원 | 8조합에서 원래 실행 버튼 복원. 별도 Tab→Enter 회귀 통과 |
| QUEUED부터 JUDGING까지 6단계·FAILED_TERMINAL | 각 상태 표시와 장부 비고 편집 가능 확인 |
| 60초 경과 → 300초 중단 → 다시 확인 | 60초 후 polling 유지, 300초 후 기존 실행 GET 재개, 접수 1회 |
| 통신 오류 → 다시 확인 | 기존 실행 조회로 복구, 접수 1회 |
| 기존 실행 404 | 자동 접수 없음, 명시적 재판정 때만 접수 2회로 증가 |
| 후보 없음·긴 근거와 연속 문자열 | 상태 표시, 긴 내용에서 패널 가로 overflow 없음 |
| 실제 Chrome 검증 script | 총 20시나리오 완료, pageerror 0건 |
| 관련 F3 브라우저 자동 회귀 | 16건 통과(95.57초), 이후 Tab 경로를 강화한 초점 회귀도 통과 |
| 타입 검사·production build·release 검사 | 통과, release 2건. 기존 bundle 크기 경고는 유지 |

전체 화면의 pixel-perfect 동일성이나 모든 접근성 기준을 통과했다는 의미는 아니다.
아래 좁은 확대 화면의 기존 제목 가림은 별도 잔여 사항이다.

[검증 원자료](f3-linux-chrome-2026-09-10/report.json),
[재현 스크립트](../../frontend/tests/manual/f3-linux-chrome.mjs).

## 실제 API·Worker·모델 연결

실제 모델 네 시나리오도 Google Chrome 실제 창으로 실행했고 모두 COMPLETED였다.
아래 시간은 클릭 후 결과 GET 응답까지이며 Worker 대기·polling을 포함한다. 각 1회의 관찰값으로
모델 성능 개선을 입증하는 통계는 아니다. 이전 턴의 Chromium 측정과 섞지 않는다.

| 시나리오 | 앵커 첫 응답 | 완료 응답 | 후보 | 최초+재열기 POST |
|---|---:|---:|---:|---:|
| 매물 | 3.964초 | 39.302초 | 3 | 1 |
| 매물 후보 없음 | 1.464초 | 10.084초 | 0 | 1 |
| 구입 | 1.491초 | 18.491초 | 2 | 1 |
| 구입 후보 없음 | 1.399초 | 5.846초 | 0 | 1 |

[실제 응답 시간 원자료](f3-linux-chrome-2026-09-10/chrome-live-ui.json).
실제 모델 4건은 조회 상한을 300초로 늘리기 전에 같은 작업 브랜치에서 수행했다.
300초 상향 후에는 결정적인 대역·가상 시계로 지속 조회와 복구를 재검증했다.
모델·프롬프트·Backend 실행 정책은 바꾸지 않았다. 300초는 **Frontend 자동 조회의 상한**으로,
모델을 빠르게 하거나 Backend 작업을 그 시점에 취소하는 설정이 아니다.

## 이번 수정

- `useCrossJudgment.ts`: `PAUSE_AFTER_MS=300_000`. 60초를 넘겨도 같은 실행을 조회하고,
  300초 이후 ‘다시 확인’은 GET만 재개한다. 통신 오류는 즉시 표시하여 사용자가 조회를 복구할 수 있다.
- `AppShell.jsx`: F3를 열 때 실제 실행 버튼을 기억하고 명시적 닫기 후 초점을 돌려준다.
  저장·상세 닫기에는 이 복원 동작을 적용하지 않는다.
- `DetailWorkspace.jsx`: 열 때 제거되고 닫을 때 재생성되는 매물 섹션 실행 버튼에 안정적인 ID를
  부여했다. 단순 DOM ref만 복원하면 제거된 버튼을 가리켜 실패하는 것을 실제 테스트로 확인했다.
- CSS·색상·간격·글꼴·판정 정보 순서는 변경하지 않았다.

## 화면 비교와 제한

| 화면 | 변경 전 | 변경 후 |
|---|---|---|
| 매물 1366 / 100% | [이전](f3-linux-chrome-2026-09-10/before-listing-1366-100.png) | [수정](f3-linux-chrome-2026-09-10/after-listing-1366-100.png) |
| 구입 1366 / 100% | [이전](f3-linux-chrome-2026-09-10/before-requirement-1366-100.png) | [수정](f3-linux-chrome-2026-09-10/after-requirement-1366-100.png) |
| 매물 1366 / 200% | [이전](f3-linux-chrome-2026-09-10/before-listing-1366-200.png) | [수정](f3-linux-chrome-2026-09-10/after-listing-1366-200.png) |
| 구입 1366 / 200% | [이전](f3-linux-chrome-2026-09-10/before-requirement-1366-200.png) | [수정](f3-linux-chrome-2026-09-10/after-requirement-1366-200.png) |

더 큰 창과 단계·오류·300초 후 재개·긴 내용 화면도 같은 산출물 폴더에 보관했다.

**잔여 사항:** 1366×768 / 200%의 매물 상세에서는 고정된 ‘주요 작업’ 영역이 F3 제목 일부를
가린다. 다음/이전·닫기·조회 복구 버튼은 초점을 받으면 화면 안에서 가림 없이 사용할 수 있으나,
제목 초점이 완전히 드러나는 조건은 충족하지 못한다. 패널 진입 직후 자동화 스크롤 없이도
[제목 가림](f3-linux-chrome-2026-09-10/chrome-200-native-open.png)을 확인했다.
[기존 dev의 같은 진입 화면](f3-linux-chrome-2026-09-10/chrome-200-native-open-before.png)에서도
제목 초점의 중심이 가려지는 것을 확인했다. 전체 레이아웃을 바꾸는 수정은 추가하지 않았으며 이 문제를 접근성 통과로 처리하지 않는다.
Windows Chrome 및 스크린리더 검증은 별도로 남는다. 최종 결과 5초 목표도 여전히 미달이다.

## 재현

Linux Google Chrome과 DISPLAY가 있는 환경에서 Frontend 의존성을 설치하고 합성 장부를 가진
수정본 5183·이전 버전 5184를 실행한다. 실제 provider 설정은 이 화면/장애 대역 검증에 필요하지 않다.
기존 개인 Chrome 프로필은 사용하지 않고 `/tmp`의 별도 프로필을 생성한다.

```bash
cd frontend
F3_CHROME_URL=http://localhost:5183/ \
F3_CHROME_BASELINE_URL=http://localhost:5184/ \
F3_CHROME_OUTPUT=/tmp/f3-linux-chrome-validation \
node tests/manual/f3-linux-chrome.mjs
node --test --test-concurrency=1 tests/f3-recovery.browser.test.mjs tests/f3-panel.browser.test.mjs
npm run typecheck
npm run build
npm run test:release
```

이 스크립트는 설정 화면으로 실제 배율을 바꾸고 같은 제품 화면의 F3 transport만 대역으로 치환한다.
인증·실제 합성 장부와 결합하므로 합성 seed의 매물 row 5·구입 row 1이 있는 전용 DB에서 사용한다.
원래 5173 프로세스나 사용자 Chrome 프로필 설정은 변경하지 않는다.

## PR 준비 후 테스트 자원 정리

사용자 요청으로 검증용 API·Worker와 5183/5184 Frontend를 종료했다. 별도 PostgreSQL 컨테이너
`f3-performance-db`와 전용 볼륨을 제거하여 `f3test`, `f3live` 및 시드·실행 결과를 삭제했다.
검증 보고서·집계 JSON·합성 화면·[Backend 로그](f3-linux-chrome-2026-09-10/backend-tests.txt)·
[Frontend 로그](f3-linux-chrome-2026-09-10/frontend-tests.txt)는 PR 산출물로 보존한다.
원시 임시 측정 폴더·비교용 체크아웃·격리 Chrome 프로필과 워크트리의 생성 캐시는 제거한다.
원래 저장소와 개발 DB, 기존 사용자 임시 파일에는 적용하지 않는다.
문서의 localhost 주소는 측정 당시 주소이며 현재 상시 실행 서비스가 아니다.
