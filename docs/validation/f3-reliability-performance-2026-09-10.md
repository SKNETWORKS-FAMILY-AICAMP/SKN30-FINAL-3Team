# F3 조회·판정 안정성 및 성능 개선 검증 — 2026-09-10

후속 사용자 요청으로 **자동 조회 상한을 300초로 변경**하고 Linux Google Chrome 실제 창 검증을
추가했다. 최신 화면·초점 복원·300초 재개 결과는 [후속 보고서](f3-linux-chrome-2026-09-10.md)를 따른다.
아래 수치와 60초 복구 설명은 최초 구현 시점의 측정 이력이다. PR 준비 후 테스트 DB·서버·
임시 실행 파일은 사용자 요청에 따라 정리했다. localhost 주소는 측정 당시 주소다.

코드와 자동 검증은 구현했으나 **Windows Chrome 검증은 미수행**이다. 화면 변경의 완료 조건을
충족한 것으로 처리하지 않는다. **최종 판정 5초 목표도 미달**이며 실제 모델 지연이 남았다.
이 문서는 사용자 승인 범위의 구현·측정 기록이며 팀의 배포·병합 승인을 의미하지 않는다.

## 환경과 영향 모듈

- 기준: 원격 `origin/dev`를 fetch한 `df5d5ba`. 브랜치 `fix/f3-reliability-performance`.
- 구현 워크트리: `/tmp/SKN30-FINAL-3Team-f3-performance`. 원래 저장소와 미커밋 파일은 보존했다.
- 수정본 Frontend `http://localhost:5183/`, API `http://127.0.0.1:8013/`, 별도 Worker 1개.
  원래 `5173`/`8000` 프로세스를 교체하지 않았다. Vite가 워크트리 소스를 제공하고 API 요청이
  8013으로 전달되는 것을 실제 응답과 실행 ID로 확인했다.
- 별도 PostgreSQL 15 컨테이너 `f3-performance-db`, 포트 55439. 자동 검증 DB `f3test`,
  실제 합성 판정 DB `f3live`. 기존 개발 DB와 분리했고 기존 migration만 적용했다.
- 기존 `infra/local/run.py`의 설정 조립 함수를 통해 개인 설정을 프로세스 메모리에 주입했다.
  개인 비밀 설정 파일을 복사하거나 원문·인증 정보를 측정 산출물에 기록하지 않았다.
- 실제 모델은 기존 F3 OpenAI provider 및 모델 설정을 그대로 사용했다. 대량 조회·장애 테스트는
  테스트 DB와 모델 대역을 사용했다. 합성 데이터는 기존 F3 seed의 L1/R1 및 후보 없음 사례다.

| 모듈 | 변경과 영향 |
|---|---|
| frontend | `useCrossJudgment`의 resume/rerun, 상태·세션 보호, `CrossMatchPanel`의 복구 버튼 동작·문구, 회귀 fixture |
| backend | 후보 SQL projection, 페이지 조립·판정/근거 조회, heartbeat와 기존 Worker/pipeline 연결, 단계·SQL·provider 계측 |
| ai | F3 facade·repair·provider 계약 검증만 수행. 소스·모델·프롬프트·알고리즘 변경 없음 |
| 문서·위키 | API 동작 설명, Backend ADR-0006, 실행 구조와 본 측정 기록 |
| data / infra | 코드·스키마·배포·클라우드 자원 변경 없음 |

현재 모델, 상위 5건, 수동 판정, 단일 Worker를 유지했다. 폐기된 자동 판정·완료 결과 재사용·
outbox·결과 목록을 복원하지 않았다. HTTP DTO와 URL은 동일하다.

## 원인과 구현

1. 이전 훅의 `retry`는 실행 캐시를 삭제하여 60초 이후 다시 확인도 POST로 만들었다.
   `resume`은 기존 실행 GET만 재개하고, 최초 실행과 명시적 `rerun`만 POST를 허용한다.
   기존 실행 404에서는 자동 접수를 하지 않는다. 결과 응답의 최신 상태를 바로 반영하며
   effect 세대·AbortController·세션 세대로 닫힌 패널/이전 계정의 늦은 응답을 막는다.
2. 결과 조회는 전체 snapshot을 응답 객체로 변환한 뒤 잘랐고, 앵커 조회에서 같은 큰 snapshot을
   중복으로 읽었다. 유효 후보의 전체 건수·순서를 먼저 유지하고 페이지 구간만 객체로 만든다.
   이미 읽은 run/header를 공유하고, 페이지에 포함된 카드의 판정·근거만 읽는다. 매물 SQL은
   실제 점수 계산에 사용하는 컬럼만 선택한다. v2/v3 snapshot과 상위 5건 정책을 유지한다.
3. 기존 300초 lease에는 실행 중 갱신이 없었다. 단계 실행 동안 30초마다 별도 Session에서
   실행 ID·사무소·소유자·시도·미만료·실행 상태를 확인하여 300초로 갱신한다.
   갱신 실패 시 생성 task를 취소하고 후속 처리를 중단한다. 완료·오류·취소 시 진행 중 갱신까지
   회수한 뒤 종료하며 저장 직전 fencing도 유지한다. 후보 카드 병렬 생성·부분 성공은 유지한다.

Model 대기 중 업무 transaction을 유지하지 않는다. heartbeat의 lock timeout은 2초,
statement timeout은 5초이며 연결 수립·pool 대기는 기존 DB 설정의 영향을 받는다.
SIGTERM은 기존대로 현재 단계를 마친 뒤 종료한다. 강제 종료 시 마지막 lease 만료 후 회수한다.
이미 외부 provider가 수신한 호출의 과금까지 취소할 수 있다는 보장은 하지 않는다.

## 조회 실측: 동일 fixture, 전후 각 30회

단위 ms. 같은 Python 환경·DB에서 컴파일/연결 warm-up 1회 후 30회 측정했다. API 값은
실제 PostgreSQL을 연결한 ASGI TestClient 경과 시간으로 브라우저 네트워크 시간이 아니다.
7200개 snapshot 후보 중 요청 페이지 크기는 20, 미판정 페이지 offset은 200이다.
첫 측정은 빌드 등과 겹쳐 변동이 커서 재측정했으며 아래 표에는 재측정 결과만 사용했다.

| 조회 | 이전 p50 / p95 | 변경 p50 / p95 | SQL 수 이전 → 변경 | SQL 합계 p50 이전 → 변경 |
|---|---:|---:|---:|---:|
| 상태 GET | 4.395 / 5.927 | 7.942 / 11.049 | 1 → 1 | 1.104 → 1.583 |
| 판정 포함 첫 페이지 | 72.043 / 104.187 | 68.123 / 90.253 | 7 → 6 | 27.091 → 32.729 |
| 판정 없는 후보 페이지 | 73.210 / 114.576 | 47.696 / 65.332 | 7 → 4 | 27.113 → 20.481 |
| 매물 후보 SQL, 15행 | 2.096 / 4.242 | 2.315 / 8.422 | 단일 SELECT 유지 | 별도 집계 안 함 |

미판정 페이지 p95는 **43.0% 감소**, 첫 페이지 p95는 13.4% 감소했다. 상태 조회와 15행 후보
SQL은 빨라지지 않았다. 계측 비용과 로컬 부하 변동이 포함되어 있고 각 요인의 인과관계를
분리하지 않았으므로 전체 API나 후보 검색의 일괄적인 속도 향상을 주장하지 않는다.
SQL 합계는 cursor execute 시간이며 fetch·JSON 역직렬화·ORM·응답 조립 시간은 제외한다.

원자료: [이전 조회](f3-reliability-performance-2026-09-10/before-queries.json),
[변경 조회](f3-reliability-performance-2026-09-10/after-queries.json).
전체 JSONB 읽기의 별도 30회 측정은 [이전](f3-reliability-performance-2026-09-10/before-snapshot.json)과
[변경](f3-reliability-performance-2026-09-10/after-snapshot.json)에 기록한다.
약 1.03MB snapshot의 p50/p95는 이전 34.378/49.301ms, 변경 35.415/51.155ms로
읽기 자체는 줄지 않았다. 이 측정은 전체 컬럼 SELECT·전송·Python JSON 변환까지의 경과 시간이다. 테이블을 분리하거나
DB 내부의 순수 JSONB 연산 시간만 측정한 값은 아니다. 큰 snapshot 전체 읽기는 여전히 남는다.

## 실제 모델: 각 조건 3회, 전후 각 12회

단위 초, **중앙값 / 최댓값**. LISTING·REQUIREMENT 각각 cold(합성 카드 무효화 후 실행)와
warm(바로 다음 수동 판정, 카드 cache hit)을 3번 반복했다. 총 24개 실행 모두 COMPLETED다.
모델 생성 내용이 확률적으로 달라지므로 판정 문장/등급의 전후 동일성을 성능 지표로 쓰지 않았다.
정렬·건수·판정·근거의 회귀는 결정적인 테스트 fixture로 검증한다.

| 앵커 / 카드 캐시 | 이전 | 변경 | Provider 호출 수 이전 → 변경, 각 3회 |
|---|---:|---:|---|
| 매물 / cold | 51.11 / 53.93 | 61.34 / 65.17 | 6,5,6 → 5,5,5 |
| 매물 / warm | 19.22 / 30.06 | 17.47 / 22.85 | 1,1,1 → 1,1,1 |
| 구입 / cold | 37.54 / 45.84 | 40.92 / 49.57 | 4,4,4 → 4,4,4 |
| 구입 / warm | 12.95 / 19.82 | 18.85 / 19.10 | 1,1,1 → 1,1,1 |

이 harness는 접수 직후 같은 프로세스에서 claim/Worker 처리를 호출하므로 실제 Worker의
2초 polling 대기는 제외한다. `pickup_ms`는 접수 시작부터 claim 완료까지이며 intake를 포함한다.
각 조건 3회의 소표본이고 provider 변동이 크므로 최종 모델 지연이 개선되었다고 결론 내리지 않는다.

변경 후 단계별 중앙값(ms):

| 조건 | 앵커 카드 | 후보 선택 | 후보 카드 | 최종 판정 |
|---|---:|---:|---:|---:|
| 매물 cold | 10443 | 36 | 18929 | 31226 |
| 매물 warm | 148 | 62 | 422 | 16808 |
| 구입 cold | 13310 | 72 | 14618 | 13849 |
| 구입 warm | 91 | 35 | 201 | 18434 |

단계마다 중앙값에 해당하는 실행이 다를 수 있어 합이 전체 중앙값과 같지 않다. 후보 카드는
병렬 호출하므로 provider 호출 시간의 합도 단계 경과 시간과 다르다. 예를 들어 변경 run 13의
후보 카드 단계는 14.888초, 개별 모델 호출 시간 합은 약 40.216초였다.

`f3_timing`은 run_id별 접수·상태·결과·Worker 단계의 wall/SQL 수·시간을 남기고,
`f3_card_cache`는 후보 카드 hit/miss를 남긴다. `f3_model_call`은 run_id·선점 시도·기능·
생성 순번·provider 호출 순번으로 repair 등 추가 호출을 연결한다. SDK 내부 HTTP 재시도와
repair 사유를 구분하는 지표는 아니며 원문이나 프롬프트를 로깅하지 않는다.

원자료: [이전 모델](f3-reliability-performance-2026-09-10/before-real.json),
[변경 모델](f3-reliability-performance-2026-09-10/after-real.json).

## 실제 수정본 브라우저 연결: Linux 보조 검증

실제 API·별도 Worker·합성 DB·실제 모델을 연결했다. 아래 값은 클릭 이후 브라우저가 결과 GET을
수신한 시점이며 polling 간격과 Worker 대기를 포함한다. 화면 paint 자체의 계측값은 아니다.

| 시나리오 | 앵커 첫 응답 | 후보 첫 응답 | 완료 응답 | 후보 수 | 최초+재열기 POST 수 |
|---|---:|---:|---:|---:|---:|
| 매물 L1 | 2.918초 | 2.918초 | 56.660초 | 3 | 1 |
| 매물 후보 없음 | 8.094초 | 해당 없음 | 17.545초 | 0 | 1 |
| 구입 R1 | 1.375초 | 1.375초 | 29.656초 | 2 | 1 |
| 구입 후보 없음 | 24.017초 | 해당 없음 | 31.564초 | 0 | 1 |

[응답 측정 원자료](f3-reliability-performance-2026-09-10/live-ui.json).
변경 후 Linux Chromium 화면은 [매물 1920](f3-reliability-performance-2026-09-10/listing-1920-linux.png),
[매물 1366](f3-reliability-performance-2026-09-10/listing-1366-linux.png),
[구입 1920](f3-reliability-performance-2026-09-10/requirement-1920-linux.png),
[구입 1366](f3-reliability-performance-2026-09-10/requirement-1366-linux.png)에 보관했다.
후보 없음 화면도 같은 산출물 폴더에 있다. 960×540 viewport로도 캡처했지만 이는 200% 브라우저
배율 검증이 아니다. CSS·PatternFly 레이아웃은 수정하지 않았다.

## 자동 검증과 재현

- Backend F3 단위·API·통합·아키텍처 테스트 **319건 통과**(68.78초).
  후보 0/5/6/7200, v2/v3, 유효 후보 순서/건수, 페이지별 객체 생성, 판정·근거 유지와
  미판정 페이지의 불필요한 SQL 제거를 검사했다. 기존 사무소 격리·삭제/무효 카드 차단도 포함한다.
- lease 테스트: heartbeat 반복·갱신 실패·task 취소/정리, 실제 별도 연결 commit, 다른 Worker
  선점 차단, 소유자/시도 fencing, 완료·실패·주차·release 시 갱신 거절을 확인했다.
  300초 초과 상태는 시작 시각을 360초 전으로 만들고 만료 시각을 제어하여 검증했다.
  실제 모델 대역 프로세스 SIGKILL 후 만료·재선점도 검증했다. 300초를 벽시계로 기다리는
  부하 테스트는 아니며 후보 일부 실패의 성공 카드 보존은 기존 통합 테스트를 사용했다.
- Frontend 타입 검사, 빠른 테스트 전체 21파일, F3 브라우저 회귀를 포함한 브라우저 28건,
  production build, release 테스트 2건 통과. 기존 bundle 크기 경고는 남아 있다.
- 새 복구 회귀 6건 중 60초 재개·404·세션 종료의 핵심 3건은 이전 소스로 실행할 때 실패하고
  수정본에서 통과함을 확인했다. 기존 retry 이름만 fixture에서 대응시켰고 이전 제품 코드는 바꾸지 않았다.
- AI 전용 환경에서 F3·아키텍처·OpenAI provider 호환성 134건 통과.
- Backend Ruff check/format 및 Backend 프로젝트 설정을 지정한 pyright 통과.

격리 테스트 DB URL을 `DB_URL`과 `TEST_DB_URL`로 동일하게 주입한 뒤 루트에서 실행한다.

```bash
APP_ENV=test DB_TARGET=test backend/.venv/bin/python -m pytest \
  backend/tests/unit/test_f3_model_timing.py backend/tests/unit/test_worker.py \
  backend/tests/unit/test_execution_lease.py backend/tests/unit/test_execution_pipeline.py \
  backend/tests/unit/test_f3_runtime.py backend/tests/api/test_f3_*.py \
  backend/tests/integration/test_agent_run_claim.py backend/tests/integration/test_anchor_position_card.py \
  backend/tests/integration/test_candidate_cards.py backend/tests/integration/test_candidate_selection.py \
  backend/tests/integration/test_brokerage_judgment.py backend/tests/integration/test_execution_lease_db.py \
  backend/tests/architecture -q
uv run --locked --project backend ruff check --fix backend
uv run --locked --project backend ruff format backend
backend/.venv/bin/pyright --project backend
ai/.venv/bin/python -m pytest ai/tests/unit/f3 ai/tests/architecture \
  ai/tests/unit/providers/test_openai_f3_http.py -q
node .github/scripts/check-skill-docs.mjs
```

Frontend 디렉터리에서 `npm run typecheck`, `npm run test:fast`, `npm run test:browser`,
`npm run build`, `npm run test:release`를 실행한다. 브라우저 fixture는 모델 대역을 사용한다.
실제 수정본은 합성 개발 세션으로 로그인하고 매물/구입 상세 → 교차 판정 → 완료/후보 없음 →
패널 닫기/재열기를 확인한다. Network에서 F3 POST가 1회이고 GET이 같은 실행 ID인지 확인한다.

조회 benchmark는 기존 합성 seed가 있는 격리 DB를 사용하며 `APP_ENV=test`, `DB_TARGET=test`,
`DB_URL`, `TEST_DB_URL`을 주입한다. 앱 초기화용 `AI_VLLM_SLLM_BASE_URL`과
`AI_VLLM_STT_BASE_URL`은 테스트 localhost 대역 주소를 주입한다(실제 호출 없음).

```bash
PYTHONPATH=backend/src:backend/tests:backend/tests/api backend/.venv/bin/python \
  backend/tests/api/benchmark_f3_queries.py --output /tmp/f3-queries.json
# 전체 snapshot 비용만 따로 측정
PYTHONPATH=backend/src:backend/tests:backend/tests/api backend/.venv/bin/python \
  backend/tests/api/benchmark_f3_queries.py --snapshot-only --output /tmp/f3-snapshot.json
```

이전 소스는 `git archive df5d5ba`로 별도 디렉터리에 풀고 동일 harness에 그 디렉터리의
backend/src·tests·tests/api를 PYTHONPATH로 지정한다. 환경·DB·fixture·반복 수를 같게 유지한다.
실제 모델 harness `backend/tests/integration/benchmark_f3_real.py`는 기존 설정 주입 방식으로
`APP_ENV=local`, 격리 localhost DB와 실제 F3 provider 설정을 주입하고 다음처럼 실행한다.
다른 Worker가 해당 DB를 소비하지 않게 한다. 이 harness는 합성 사무소의 카드 cache를
무효화하므로 `--confirm-isolated`가 필수이며 합성 전용 DB에서만 실행한다.

```bash
PYTHONPATH=backend/src backend/.venv/bin/python backend/tests/integration/benchmark_f3_real.py \
  --confirm-isolated --label after --output /tmp/f3-real.json
```

## 미완료 조건과 남은 병목

**Windows Chrome은 검증하지 못했다.** computer-use 스킬을 읽고 필수 node_repl 초기화와
reset 후 재시도했으나 스크립트 실행 전에 다음 연결 오류가 반복되었다.

```text
codex/sandbox-state-meta: sandboxCwd is not a local file URI:
file:///home/hong/project/ai-camp-project-note/projects/SKN30-FINAL-3Team
```

이는 승인 거절이 아니라 Windows 자동화 도구의 작업 경로 연결 오류다. 유효한 변경 전후
Windows 스크린샷 비교를 만들지 못했다. Linux 결과로 대체 통과 처리하지 않는다.
Windows 연결이 정상인 환경에서 다음 항목을 완료해야 한다.

- 실제 Chrome 100%, 1920×1080/1366×768에서 같은 합성 데이터와 기존 코드/수정 코드 비교.
- 실제 Chrome 200% 배율의 핵심 버튼·내용 접근, 긴 문장 줄바꿈·스크롤·잘림·레이아웃 이동.
- 매물/구입 상세의 실행 단계·완료·후보 없음·오류·60초 재개·페이지 이동·패널 재열기.
- 키보드 접근과 포커스 복원, 판정 중 장부 편집 가능 여부. 색상·간격·폰트·패널 크기·등급 표시 유지.

최종 판정 5초는 cache hit에서도 달성하지 못했다. 모델·프롬프트·상위 5건·Worker 수를 그대로
유지한 범위에서는 SQL 최적화가 수십 초의 모델 대기를 제거하지 못한다. 앵커·후보 선표시가
최종 완료보다 빠르다는 것은 확인했으나 cold 앵커 자체도 5초를 넘을 수 있다. 전체 JSONB
fetch/역직렬화, 모델 생성·repair 변동, polling 최대 5초가 남은 병목이다. 모델 변경·스키마 분리·
실행 구조 확장은 이번 구현에 포함하지 않았다.
