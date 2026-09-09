# 테스트 실행·회귀 검증 개선

상태: 코드 구현. 실제 외부 모델 재평가와 공유 dev 배포는 수행하지 않았다.
기준: `4b5d002`, 2026-09-09 사용자 로컬 기능 점검 보고서와 테스트 정적 감사.

## 범위와 수량

앞선 정적 감사의 `1d44019`에는 테스트 파일이 139개였다. 이번 작업의 시작점에는
후속 F3 테스트가 추가돼 140개이며, 개선 후 148개다. Fixture·설정·평가 데이터는 제외한다.
파일 수를 줄이는 대신 실행 누락을 없애고 실제 실패 경계의 검증을 보강했다.

| 영역 | 시작 파일 수 | 개선 후 파일 수 |
|---|---:|---:|
| Backend | 61 | 63 |
| AI | 27 | 29 |
| Frontend | 24 | 24 |
| Infra | 25 | 25 |
| GitHub 도구 | 3 | 7 |

- PR 검토 도구 테스트는 책임별 5개 파일로 분리했다. 기존 51개 테스트 본문을 보존했다.
- Backend 앵커 카드·중개 판정 테스트의 준비 코드를 분리하고 실제 commit 정리 수명주기를
  공유한다. 기존 43개 테스트 본문·데코레이터와 다른 연결의 가시성 검증을 보존했다.
- Infra HTTP 보호 검사 3개는 `infra/serving/tests/test_runtime.py`에서 한 번만 관리하며
  로컬 `just check`와 기존 이미지 게시 검사에서 실행한다.
- 개선 후 수작업 테스트 파일은 모두 1,000줄 이하다. 일반 소스 전체를 분리한 작업은 아니다.

## 로컬 보고서에서 보강한 회귀 경계

| 보고된 문제 | 수정·검증 경계 |
|---|---|
| OpenAI F3 스키마 거부 | 실제 F3 DTO를 SDK HTTP 직렬화까지 전달하고 전송 스키마와 원본 DTO 재검증을 확인. 외부 API는 합성 응답으로 대체 |
| 비고 저장으로 상담 로그 중복 | 화면에 읽은 상담 내용과 최신 서버 로그를 비교. 매물·구입장 저장 요청의 로그 추가 횟수 확인 |
| 저장 후 F3 자동 재접수 | 저장 시 패널 닫기, 열린 패널의 입력 버전 변경은 명시 재요청 대기. 자동 POST 발생 여부 확인 |
| 챗봇 만기 근거 거절 | 만기·만료 동의어와 일정 대상 구분 확인. 모호한 대상은 임의 추정하지 않음 |
| 구입장 검색 미연결 | 공통 검색 입력이 실제 표시 행에 반영되는지 Chromium 확인 |
| 캘린더 dialog 접근성 | 한 번에 하나의 dialog만 활성화하고 입력 포커스·목록 복귀 확인 |
| 매물 비고 검색 건수 불일치 | 별도 검색식을 복제하지 않고 그리드의 표시 행 수를 건수로 사용 |

구입장 브라우저 검증 중 서버 저장 후 `carrySavedIdentity` import 누락과 저장 도중
상세 prop의 낙관 갱신으로 완료 표시가 앞서는 경로도 발견해 수정했다.

Frontend 세부 실행 명령과 브라우저 검증 범위는 [Frontend 검증](../../frontend/TESTING.md),
DB·인증·F2 입력·실제 commit 검사는 [Backend 품질 문서](../../.agents/skills/backend/references/testing-and-quality.md),
OpenAI 전송 규칙은 [AI ADR-0006](../../.agents/skills/ai/references/decisions/ADR-0006-openai-structured-output-schema.md)에서 관리한다.

## 추가 검증과 해석 범위

- F2 평가 산식은 작은 정답표의 TP·FP·FN·파싱 실패·빈 입력으로 검증한다.
  전체 평가와 분류 전용 평가의 서로 다른 분모 규칙을 혼동하지 않는다.
- 실제 F2 analyzer에 가짜 Provider를 주입해 전사만 전송하고 장부 원본값을 보내지 않는지 확인한다.
- 챗봇은 입력 예산과 별도로 Provider가 반환한 실제 token 사용량의 경계·초과를 검증한다.
- F2 HTTP 분석만으로 업무 행을 저장하지 않고, 승인 후 장부 저장으로 접수된 F3 실행을
  명시 요청이 재사용하는 실제 PostgreSQL 통합 흐름을 추가했다. 브라우저 필드 변환이나
  Worker 판정 완료까지 포함하는 종단간 테스트는 아니다.
- DB 검증은 이번 작업만의 임시 PostgreSQL에서 수행한다. 기존 로컬 진단 DB·서버를 사용하지 않는다.
- 상담 로그 저장 후 조회 실패 복구는 상세를 닫고 그리드에서 재시도하는 경로를 검증한다.
  상세 안에서 실패 직후 재시도, 저장 중 추가 입력 보존, 늦은 F3 응답과 화면 닫기의 경합까지
  이번 브라우저 회귀가 검증했다고 해석하지 않는다.
- 과거 실제 모델 성공률과 이번 합성 회귀 결과를 합쳐 현재 모델 품질로 보고하지 않는다.
  F3 실제 후보·근거·피드백의 외부 모델 연결, F2 실제 음성 품질, 공유 dev 배포 검증은 별도다.

## 실행 결과

2026-09-09, 격리 워크트리·합성 입력으로 실행했다. DB 관련 환경변수는 임시 테스트 DB로
지정했다. 테스트 개수는 파라미터 확장 후의 실행 사례이며 위의 파일 수와 다르다.

| 검사 | 결과 |
|---|---|
| `uv run --locked --project backend pytest -q backend/tests` | 755 통과, skip 0. 임시 PostgreSQL 사용 |
| `uv run --locked --project ai pytest -q ai/tests` | 454 통과 |
| Backend·AI Ruff check/format 및 Pyright | 통과 |
| 빈 임시 DB의 Yoyo migration 및 재적용 | 두 번 통과 |
| Frontend `npm run test:fast` | 21개 파일, 216 사례 통과 |
| Frontend `npm run typecheck`, `npm run build`, `npm run test:release` | 통과, 릴리스 검사 2 사례 |
| Frontend 브라우저 | 전체 묶음 17개 중 16 통과. 캘린더의 포커스 복귀 대기 조건을 고친 뒤 해당 1개 통과. 수정 후 전체 묶음 재실행은 하지 않음 |
| Infra `tests/`, `runpod/tests/`, `serving/tests/` | 각각 206·36·23 통과 |
| `node --test --test-isolation=none .github/scripts/tests/*.test.mjs` | 61 통과 |
| `node .github/scripts/check-skill-docs.mjs` | 오류 0 |
| `just --fmt --check -f infra/justfile`, `git diff --check` | 통과 |

제한된 실행 환경에서는 Node 자식 프로세스·로컬 소켓이 차단되거나 일부 비동기 검사가
정지했다. 해당 프로세스를 종료한 뒤 로컬 통신을 허용한 환경에서 검증했으며, 실제 외부
Provider·클라우드 변경을 수행하지 않았다. 임시 테스트 DB는 검증 후 제거했다.

캘린더 검사에서는 dialog가 숨겨지는 시점과 다음 animation frame의 포커스 복귀 시점이
달랐다. 즉시 단언을 실제 `activeElement` 복귀 조건 대기로 고쳤으며 고정 sleep을 추가하지 않았다.
Frontend 실행 로그는 `/tmp/frontend-{fast,typecheck,build,release}-verified.log`,
브라우저 전체·캘린더 재검증 로그는 각각 `/tmp/frontend-browser-verified.log`,
`/tmp/frontend-calendar-verified.log`다. 로컬 로그는 저장소 산출물이 아니다.
