---
status: 구현됨
updated: 2026-09-09
---

# F3 1차 확장 구현과 검증

이 문서는 별도 구현 PR의 코드와 검증 결과를 설명한다. 사용자 요청으로 문서·구현 PR을
분리했으며 두 PR을 함께 검토한다. 문서 PR만 병합해도 아래 기능이 dev에 배포되는 것은 아니다.
문서 브랜치에 없는 새 코드·SQL 링크는 구현 커밋을 직접 가리킨다.

사용자 요청에 따라 별도 워크트리에서 최신 `origin/dev`의 `f700f5a`를 먼저 병합하고 구현했다. 원본 checkout의 코드를 변경하지 않았고 공유 dev DB/앱·GPU에도 적용하지 않았다. 후속 시드 요청에 따른 기존 로컬 DB 적용은 아래 별도 절에 기록한다. [기능 정의](../../requirements/f3/judgment-results-list.md), [화면](../../screen/f3-judgment-results.md), [ADR-0035](../../../.agents/skills/project-wiki/references/decisions/ADR-0035-f3-conditional-automation-results.md)가 이번 범위의 정본이다. 팀 병합과 공유 환경 배포는 별도다.

## 사용자에게 제공하는 기능

공통 ‘교차 판정’ 메뉴에서 매물/손님 기준의 저장 결과를 확인한다. 대상별 대표 후보, 최신 연결·강함·미판정·확인 필요 필터, 담당자·단지·거래유형·검색과 페이지를 제공한다. 장부 상세에서는 요약과 결과 보기를 제공하며 후보 상세에서 양쪽 포지션 카드·판정 근거·기존 상담/피드백을 확인하고 원장으로 이동한다. 기존 PatternFly 6 컴포넌트와 테마를 사용했다. 모바일은 전체 본문 영역과 화면 안의 결과 패널·닫기 버튼·긴 후보명 줄바꿈을 확인했다.

화면 진입·새로고침은 GET만 수행한다. 명시적 최신 분석 요청은 기존 POST를 사용하지만 유효한 완료 실행이나 진행 실행을 재사용한다. 결과가 오래되어도 마지막 성공 결과를 보존하며 공개 불가·미생성·정상 무후보·미판정을 구분한다. 상위 5건 초과 AI 판정·연락 자동 발송·챗봇 도구 활성화는 이번 범위가 아니다.

## DB 변경: 결과 저장은 기존에도 존재

| 구분 | 테이블/컬럼 | 책임 |
|---|---|---|
| 기존 | `agent_run` | 실행 상태·lease·시도·최소 입력 참조 |
| 기존 | `negotiation_position_analysis`, `negotiation_position_price`, `negotiation_position_evidence` | 양측 포지션 카드와 가격·근거 |
| 기존 | `match_evaluation` | 후보 집합 snapshot·판정 결과 헤더 |
| 기존 | `match_candidate_evaluation`, `match_candidate_evidence` | 후보별 등급·이유·순위·근거 |
| 추가 | `match_source_revision` | 사무소별 원천 변경 버전 |
| 추가 | `match_change_outbox` | 원장 저장과 원자적으로 기록하는 병합 이벤트 |
| 추가 | `match_target_state` | 대상별 최신 성공 결과 포인터·검증 identity·갱신 대기 상태 |
| 기존 확장 | `agent_run.priority`, `next_attempt_at` | 사용자 요청 우선 처리·재시도 시각 |

[Migration 020](https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN30-FINAL-3Team/blob/e785db47492b1680d7cbf0c76bfe3eca45c5c73b/docs/db/migrate/020_CREATE_F3_AUTOMATION.sql)을 적용하면 총 34테이블이다. 결과 본문을 새 테이블에 복제하지 않고 기존 `match_evaluation.id`를 공개 `result_id`로 쓴다. 이전에는 결과를 저장해도 완료 실행을 접수 때 재사용하지 않았고 브라우저가 기억한 run 중심으로 접근했다. 이번 변경은 그 결과를 발견·재사용하고 현재 입력과 일치하는지 관리한다.

## 이벤트·Worker와 서버 분리

기존에도 모델 호출은 저장 HTTP handler 밖의 Worker에서 수행했다. 이번에는 F1 commit 뒤 F3 접수하던 DB 작업을 원자 trigger/outbox로 바꾸었다. 저장은 모델을 기다리지 않지만 revision/outbox SQL과 잠금 비용은 남는다. 기록 실패는 저장도 rollback한다.

자동 활성화 시 유효 대상의 의미 있는 변경만 실행하고 연속 변경을 기본 3초 병합한다. 상담/관계/단지/후보 변화, UTC 날짜와 모델 구성도 검증한다. 반대편 새 후보를 놓치지 않도록 사무소 양쪽 장부를 보수적으로 재검증하되 같은 의미 입력은 모델을 재호출하지 않는다. 모델 응답 뒤 최종 입력·lease를 확인해 구버전 결과의 최신 게시를 막는다.

**API와 Worker는 같은 EC2에서도 별도 프로세스/컨테이너다.** Worker 내부에는 모델 실행과 독립된 이벤트 소비 스레드 및 lease 갱신 스레드가 있다. API 안의 백그라운드 스레드로 Worker를 실행하는 구조가 아니다.

여러 host의 Worker가 같은 PostgreSQL에 연결해 선점할 수 있고, 전역 DB advisory 슬롯 1개로 F3 모델 실행을 제한한다. lease 300초를 30초마다 갱신하며 만료 작업 복구·최대 3회 claim·재시도 대기·사용자 우선순위를 제공한다. 모델 대기 동안 슬롯용 autocommit 연결은 유지하지만 DB transaction/row lock은 유지하지 않는다.

이는 Worker 분리 배치가 가능한 도메인 경계다. Worker EC2/ASG·독립 배포·권한·보안그룹·관측 설정까지 자동 구성한 것은 아니다. 현 단일 API의 챗봇 동시 실행 1건과 F3 후보 카드 최대 5건은 같은 general 모델에서 경합할 수 있다. Worker 수 증가만으로 전역 슬롯 상한이 증가하지 않으며 다중 API로 확장할 때는 챗봇 동시성 제한도 공유화해야 한다.

GPU 상시 운영이라는 사용자 전제에서 같은 가동시간의 임대료 증가는 자동 판정의 핵심 비용이 아니다. 모델 처리량·대기·DB/CPU·외부 유료 Provider 호출량은 여전히 계측해야 한다. 실제 공유 GPU p95와 사용자 대기 개선량은 이번 테스트 모델 검증으로 측정하지 않았다.

## local/dev 자원과 적용 순서

새 AWS 자원·SQS·Redis·추가 GPU는 필수가 아니다. 로컬은 PostgreSQL 15+pgvector 컨테이너, API와 Worker 별도 명령, Frontend로 실행한다. dev는 기존 EC2 API/Worker·RDS·상시 general 모델 서버를 사용한다. [로컬 실행 안내](../../../infra/local/README.md), [운영 설정](../../../infra/operations/configuration.md), [Backend README](../../../backend/README.md)를 따른다.

1. DB migration 021까지 먼저 적용하고 호환되는 Backend/Worker를 배포한다. 이전 schema에 새 코드를 실행하지 않는다.
2. 기본 `F3_AUTO_JUDGMENT_ENABLED=false`에서 GET·명시적 분석·권한을 확인한다.
3. 모델 설정·기존 합성 opt-in·작업 여유 용량을 확인한 후 Worker에 자동 flag를 활성화한다. `F3_AUTO_DEBOUNCE_SECONDS=3`, `F3_AUTO_BATCH_SIZE=20`이 기본값이다.
4. 초기 이벤트와 날짜/설정 sweep의 제한된 backfill을 관측한다. 문제가 있으면 flag를 꺼 자동 소비를 멈춘다. 이미 접수된 작업·저장 이벤트를 삭제하는 스위치는 아니다.

개발 브랜치의 설정 파일만 수정했으며 Terraform apply·공유 DB migration·배포는 수행하지 않았다. 롤백을 위해 migration을 임의 삭제하면 outbox/참조를 잃을 수 있으므로 flag 중단과 이전 앱 호환성 검토를 우선한다.

## 검증 환경과 재현

격리 로컬 PostgreSQL의 합성 원장 36개·구입장 48개에 migration 001~020과 seed 검증을 적용했다. 브라우저 DB는 `f3_expansion_validation`, 자동 테스트 DB는 별도의 `f3_automation_test`다. 서비스 검증은 Frontend 5178→API 8103→DB 55439의 실제 연결이다.

모델 연결 실검증은 인증 오류로 성공하지 못했다. 사용자가 **‘테스트 모델 통합 검증으로 진행’**을 지정하여 이후 모델 응답만 명시적 deterministic generator로 교체했다. 운영 코드에 가짜 응답 fallback이나 모델 우회 설정을 추가하지 않았다. 실제 모델 품질·지연 검증 성공으로 해석하지 않는다.

```bash
# 실제 HTTP 저장 → outbox → Worker → DB → 결과 GET (로컬 *_validation/합성 seed만 허용)
uv run --locked --project backend python backend/scripts/f3_browser_validation.py --confirm-synthetic-validation

# 위에서 저장한 양방향 결과를 실제 Chromium UI로 검증 (frontend/에서)
F3_REAL_INTEGRATION=synthetic-local-validation \
F3_VALIDATION_DATABASE=f3_expansion_validation \
node tests/f3-real-integration.browser.mjs
```

브라우저 제어 도구의 초기화가 로컬 경로 오류로 실패하여 저장소 Playwright API와 Chromium을 사용했다. 브라우저 테스트는 HTTP 응답을 가로채거나 mock하지 않는다. 검증용 Worker runner만 모델 호출을 대체하며 HTTP 저장·PostgreSQL commit·Worker 선점/lease·pipeline·결과 게시는 실제 코드다.

## 확인한 결과

| 검증 | 결과/범위 |
|---|---|
| Backend 최종 통합 묶음 | **592 passed**: 전체 unit/architecture, F3 API, F1 장부 API, 자동화·선점·판정·카드·후보·backfill PostgreSQL 회귀 |
| 신규 자동화 | 위 묶음에 포함된 14개: 원자 rollback·중복/병합·새 후보·완료/최종 AI 입력 재사용·의미 없는 수정·늦은 게시 차단·lease 복구·독립 DB 슬롯·날짜 재검증 |
| 신규 결과 API | 위 묶음에 포함된 15개: 조회 무접수·최신성/공개 불가·미판정/후보 페이지·권한·cursor·비활성 대상·과거 snapshot·삭제 부모의 상담 차단 |
| Frontend 빠른 검사 | 222 passed. 새 조회 DTO·필터·기존 기능 회귀 포함 |
| Frontend 상태 회귀 | mock 기반 F3 브라우저 12개 시나리오: GET 무접수, 편집 보호, 피드백, 권한 회수, terminal 상태, cursor 복구 등 |
| 실제 Worker 양방향 | LISTING L1: AUTO_CHANGE run 3/result 3, 후보 3·강함 1·기각 2. REQUIREMENT R1: run 4/result 2, 후보 2·강함 1·기각 1. 둘 다 CURRENT |
| 실제 브라우저 | 양방향 목록/Drawer·카드, 새로고침 10회 POST 0건, 장부 복귀, 정확한 원본 상담, 피드백 201/DB PAIR 기록, 독립 세션 결과 복원. 390px 화면/패널 내부 가로 넘침 0·닫기 버튼 화면 내·pageerror 0 |
| 정적 검사 | Backend Ruff·Pyright, Frontend TypeScript·build, Terraform 설정 fmt와 문서 상대 링크를 확인 |

테스트 모델은 자동 판정 필요성과 결과 정합성·연동을 검증하며 추천 품질을 검증하지 않는다. 결과 ID는 이 격리 DB의 관측값이지 운영 고정값이 아니다. 일반 Provider 장애와 모델 품질/처리량, 다중 EC2 실제 배포, 실제 중개사 조사, 준비된 결과 비율·챗봇 p95·대형 사무소 SQL 성능은 후속 검증이다.

목록은 최소 표시정보와 최신 실행을 일괄 조회한 뒤 서버에서 필터/페이지를 적용한다. 행별 N+1과 브라우저 F1 전수 로딩에 의존하지 않지만 대규모 SQL 집계 projection을 구현한 것은 아니다. 단건 결과는 요청 대상/후보 ID로 조회를 제한한다.

최종 실제 브라우저의 [검증 결과 JSON](../../validation/f3-expansion-2026-09-09/browser-report.json), [데스크톱 캡처](../../validation/f3-expansion-2026-09-09/browser-final.png), [모바일 캡처](../../validation/f3-expansion-2026-09-09/browser-mobile.png)를 보존했다. 로그인 전 세션 확인의 예상된 401 외 console error는 없었다.

## 매칭 도메인 테이블 명명

추가 테이블 이름에서 요구사항 번호를 제거하라는 사용자 요청에 따라 `match_source_revision`, `match_change_outbox`, `match_target_state`로 변경했다. 기존 `match_evaluation` 도메인과 일치시켰다. [Migration 021](https://github.com/SKNETWORKS-FAMILY-AICAMP/SKN30-FINAL-3Team/blob/e785db47492b1680d7cbf0c76bfe3eca45c5c73b/docs/db/migrate/021_ALTER_MATCH_AUTOMATION_NAMES.sql)은 020의 적용 이력을 보존하고 데이터·FK·인덱스·trigger/function을 rename한다. 현재 코드는 021 적용 DB를 사용하며 공유 dev에는 적용하지 않았다.

명명 변경 검증: 기존 검증 DB 2개에 021을 적용해 각 테이블의 전체 행이 변경 전후 동일함을 확인했다(브라우저 DB의 대상 상태 84건 보존). 빈 일회용 DB의 001~021 적용, 새 테이블 3개·트리거 9개와 이전 객체명 제거를 확인하고 해당 일회용 DB는 제거했다. 변경 후 PostgreSQL API/Worker 회귀 **214개**, 실제 브라우저 통합 9개 점검, Ruff·Pyright·문서 검사를 통과했다.


## 후속: 장부별 예시 결과 시드와 기존 로컬 DB

[사용자 후속 요청](../../requirements/sources/f3-expansion-seed-2026-09-09.md)에 따라 기본
`seed-f3-synthetic` 명령을 장부·예시 매칭 결과 생성까지 확장했다. 새 상태 테이블의 FK를
고려해 reset 순서를 보완하고, 원장 DELETE trigger로 만들어진 해당 사무소의 outbox/revision은
마지막에 정리한다. 실행·카드·판정은 실제 저장 파이프라인을 거치며 생성기만 결정적 합성
구현을 사용한다. 상세 절차와 공유 dev 명령의 모델 프로필 경계는 [시드 안내](../../db/seed/README.md)가 정본이다.

실행 이력에는 `synthetic_fixture` 출처를 남기고 공개 API에는 `is_synthetic_fixture`를 제공한다.
화면은 ‘시드 예시 결과’와 실제 모델 추론이 아니라는 설명을 표시한다. 시드 전용
prompt/workflow 버전으로 실제 모델 카드·판정 캐시와 분리했다. 기존 활성 모델 설정은
선택한 프로필을 유지하고, API/Worker에 가짜 모델 fallback을 만들지 않는다.

최종 적용 대상은 기존 **127.0.0.1:5432 / brokerage**다. 원본 checkout의 private DB 설정에서
대상을 확인한 뒤 기존 migration 019에 020·021을 적용했다. 이전 검증용 55439 DB는 최종
시드 반영 대상이 아니다. 워크트리 API 8103과 Frontend 5178이 기존 DB를 사용한다.
사무소·사용자 ID 2와 `f3_synthetic_dev`를 유지했다. 다른 사무소 30개 테이블의 기존 행 10건은
마이그레이션으로 추가된 기본값 컬럼을 제외한 기존 컬럼의 전후 해시가 동일하다.

| 기존 DB에 반영·확인한 항목 | 결과 |
|---|---|
| 원장·대상 | 매물 36, 구입장 48, `match_target_state` 84 |
| 완료 예시 | 적격 81개 모두 CURRENT, 종료 2개 INELIGIBLE, 미지원 구분 1개 INSUFFICIENT_INPUT |
| 전체 후보·판정 | 후보 868, 예시 판정 365(강함 348·약함 8·기각 9), 미판정 503 |
| 정상 후보 없음 | 적격 완료 결과 4개 |
| SQL 검증 | 장부 30개·결과 12개 PASS |
| 반복 결과 생성 | 기존 CURRENT 81개 재사용, 신규 실행/결과 0개 |
| 시드 계정 브라우저 | 실제 `/me`에서 `f3_synthetic_dev`·사무소 2, 양방향 목록/상세·시드 배지·무후보·미판정 확인 |
| 조회의 부수 효과 | 새로고침 10회 포함 run POST 0, feedback POST 0, 기타 쓰기 0; 로그인은 개발 세션 발급 API 사용 |
| 브라우저 오류 | pageerror 0, 예상 밖 console error 0. 로그인 전 `/auth/me` 401은 정상 |
| 자동 회귀 | Backend unit/architecture 331, 결과 API 16, 시드 PostgreSQL 통합 6, Infra 22, Frontend 빠른 검사 223 PASS |
| 정적 검사 | Backend Ruff·Pyright, Frontend typecheck/build, Infra 변경 Python Ruff, 문서 링크·diff 검사 PASS |

Backend 추가 단위 검사는 제한 환경에서 이벤트 루프 대기 후 중단했으며, 로컬 실행에 필요한
권한으로 다시 실행해 331개를 통과했다. 시드 통합 6개는 기존 격리 테스트 DB에서 실행했다.
전체 SQL seed의 81 CURRENT·12개 검증과 L1의 R1/R2/R3 강함·약함·기각,
다른 사무소 보존, 완료 재사용, 실제 버전의 카드·판정이 예시 캐시를 재사용하지 않는 것을 검증한다.

```bash
# 기존 로컬 DB 시드를 연결한 API 8103/Frontend 5178 실행 후 frontend/에서
F3_SEED_INTEGRATION=existing-local-synthetic-seed \
F3_SEED_LOGIN_ID=f3_synthetic_dev \
node tests/f3-seed-integration.browser.mjs
```

[DB·시드 결과 보고서](../../validation/f3-expansion-2026-09-09/seed-existing-local-report.json),
[브라우저 보고서](../../validation/f3-expansion-2026-09-09/seed-browser-report.json),
[양방향 결과 화면](../../validation/f3-expansion-2026-09-09/seed-browser-listing.png),
[미판정 화면](../../validation/f3-expansion-2026-09-09/seed-browser-unjudged.png)을 보존했다.
공유 dev에는 적용하지 않았으며 실제 모델 품질·지연은 이 시드 검증 결과에 포함하지 않는다.
