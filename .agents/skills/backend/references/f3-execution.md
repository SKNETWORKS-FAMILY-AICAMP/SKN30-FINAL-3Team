---
status: 구현됨
updated: 2026-09-09
---

# F3 실행 경계와 확장

현재 작업 브랜치는 최신 dev `f700f5a`를 병합한 뒤 조건부 자동 판정·저장 결과 조회를 구현했다.
아래 리팩토링 경위와 이전 PR 검증 수치는 당시 기록이며, 현재 확장 동작은 구현 구조와
서버 운영 절을 따른다. 공유 dev에 적용·배포했다는 의미는 아니다.

## 리팩토링 판단과 범위

최신 `dev`의 `1d44019`를 병합한 작업 브랜치에서 검토했다. F3는 이미 영속 작업·Worker,
AI facade, 입력 준비/모델 호출/검증 저장의 경계가 있으므로 이 구조를 유지한다.
사용자가 2026-09-09 필요한 리팩토링의 구현을 위임했다. 팀 공유 승인 전 브랜치의 구현 기록이며,
[ADR-0001](decisions/ADR-0001-contextual-architecture-defaults.md)의 복잡도에 비례한 구조를 적용했다.

필요한 변경은 책임 분리와 재시도 버그 수정이다. 1,665줄 Repository가 작업 선점·장부 입력·
카드·판정을 함께 소유했고, Worker가 프로세스 수명주기와 모델 조립을 함께 담당했다.
실행 상태별 단계 선택도 pipeline과 조립 코드에 중복됐다. 기능 확장 시 이 경계의 변경 이유가
다르므로 모듈로 분리했다. 전달만 하는 service/repository 클래스와 범용 워크플로 엔진은 추가하지 않았다.

## 구현 구조

경로는 저장소 루트 기준이다.

| 책임 | 구현 | 변경 시 기준 |
|---|---|---|
| 기동·종료·polling·실행별 격리 | `backend/src/worker.py` | 프로세스 수명과 공유 event loop 소유 |
| 변경 이벤트·자동 재검증 | `automation.py`, migration020~021 | 원장과 원자 outbox, 3초 병합, 별도 소비 세션, 제한된 배치 |
| 최신성·완료 결과 재사용 | `freshness.py` | 원천 revision·UTC·구성 fencing과 실제 입력 지문 비교 |
| 최종 AI 입력 재사용 | `judgment_cache.py` | 동일 양측 카드·판정 바인딩만 재사용하고 저장 DTO 재검증 |
| 결과 목록·상세 조회 | `judgment_queries.py`, `judgment_targets.py`, `judgment_content.py` | GET은 조회만 수행, 기존 공개·tenant 검증 유지 |
| 실행 슬롯·lease 갱신·이벤트 소비 수명 | `backend/src/f3_worker_reliability.py` | DB 전역 F3 슬롯과 독립 heartbeat·consumer 세션 |
| 모델 route·provider·AI facade 조립 | `backend/src/f3_runtime.py` | DB 모델 설정으로 필요한 capability만 생성; Worker 밖 조립 진입점 |
| 저장 상태 → 다음 단계 | `backend/src/domain/agent_execution/execution_policy.py` | dispatch·capability·실패 단계가 같은 매핑 사용 |
| 단계 호출·재시도·오류 처리 | `backend/src/domain/agent_execution/pipeline.py` | 상태 변경은 유스케이스의 DB 검증과 함께 수행 |
| 입력 준비·AI 호출·재검증 저장 | `anchor_card.py`, `candidate_cards.py`, `judgment.py` | 모델 호출 동안 DB transaction을 열지 않음 |
| 영속 작업·lease·상태 전이 | `repository/runs.py` | advisory lock, SKIP LOCKED, owner/attempt/expiry fencing 유지 |
| 장부·상담 범위·현재 입력 | `repository/inputs.py` | 사무소·측면별 조회 범위와 source identity 유지 |
| 카드 캐시·가격·근거 | `repository/cards.py` | cache key 고유성·유효성 검증 유지 |
| 후보 SQL 검색 | `repository/candidate_search.py` | 결정적 후보 범위, 이후 점수 계산은 `candidates.py` |
| 모델 설정·실행 바인딩 | `repository/model_configs.py` | 안전한 snapshot과 실행 중 버전 고정 |
| 판정·후보 근거·피드백 | `repository/evaluations.py` | 기존 tenant·루트 실행 격리 유지 |

위 표의 짧은 Python 경로는 `backend/src/domain/agent_execution/` 아래다.
`repository/__init__.py`는 명시적인 공개 re-export만 제공한다. 기존 application 호출의
`from domain.agent_execution import repository`는 유지되며, SQL 모듈은 facade를 역참조하지 않는다.
기존 SQL 함수·자료형의 본문은 옮기고 공개 호출 경계를 유지했다. 트랜잭션 commit/rollback은
기존 유스케이스가 계속 소유한다.

`execution_policy`는 저장 상태에서 다음 단계를 선택한다. F1 저장 요청은 AI나 후속 접수
함수를 호출하지 않고 원장 transaction 안의 DB trigger로 revision과 outbox를 기록한다.
`F3_AUTO_JUDGMENT_ENABLED=true`인 Worker는 유효한 대상만 `AUTO_CHANGE` 전체 판정으로
접수한다. 비입력 메모·담당자 수정과 같은 값 저장은 이벤트를 만들지 않는다. outbox 기록이
실패하면 원장 저장도 rollback한다.

기존 `LEDGER_SAVE` 실행과 내부 backfill 함수의 CARD_ONLY 주차·사용자 승격은 호환을 위해
유지한다. 신규 F1 HTTP 경로는 `triggers.py`를 호출하지 않는다. 진행 작업은 재사용하며,
검증 가능한 완료 결과도 재사용한다. 전체 SQL 후보가 달라져 새 결과 snapshot이 필요해도
최종 상위 5건의 카드와 바인딩이 같으면 저장 판정을 재검증해 모델 호출을 생략한다.

원천 revision은 소비 지연 중에도 이전 결과를 STALE로 만드는 사무소 단위 보수적 토큰이다.
Worker는 실제 앵커·선택 후보 입력과 전체 SQL 후보 집합을 비교해 무관한 변경의 추론을
생략한다. 새 상대 후보 유입은 기존 후보 역참조에 한정하지 않고 재검증한다. 원장 데이터와
설정·UTC 변경은 저장 직전 fencing하고, 비입력 수정으로만 증가한 row_version은 신규
실행의 의미 입력 변경으로 취급하지 않는다. 기존 실행은 이전 row_version 검증을 유지한다.

## 후보 카드 부분 실패 수정

최대 5건의 cache miss 모델 호출은 병렬이며 입력 준비와 저장은 순차다.
이전에는 앞 후보의 생성이 실패하면 저장 루프가 중단되어 뒤 후보의 성공 응답도 버려졌다.
이제 생성 실패 항목만 건너뛰고 다른 성공 카드는 기존 lease·입력 검증을 거쳐 각각 저장한다.
하나라도 실패하면 첫 생성 오류를 전달하고 `CANDIDATES_READY`를 유지한다. 성공한 일부 후보만으로
판정을 시작하지 않으며, 재시도는 유효 캐시를 재사용하고 누락 카드만 생성한다.

입력 변경이나 lease 상실 등 **저장 검증 실패**는 즉시 중단한다. 생성 성공이라는 이유로 검증을
건너뛰지 않는다. 전체 성공 시 후보 순서와 최종 snapshot 형식은 기존과 같다.
현재 단계 실패 시 소모한 토큰은 실행 합계에 완전히 집계되지 않을 수 있다. 이 수정은 호출 유실을
줄이며 사용량 계측 보완이나 동일 cache key의 동시 AI 호출 방지를 구현하지는 않는다.

## 서버 운영과 확장 경계

API와 Worker는 동일 image를 쓰는 별도 프로세스·컨테이너다. 같은 EC2 배치는 현재 dev
구성이며, 작업 분배·재개·최신 결과 포인터는 PostgreSQL이 소유한다. Worker 내부의 이벤트
소비 스레드는 2초마다 독립 Session에서 outbox를 처리하므로 느린 모델 응답을 기다리지 않는다.
UTC·구성 재검증 sweep은 60초 간격이며 배치 기본값은 20이다. 소비 오류는 안전한 분류만
로그하고 내구성 상태에서 재시도한다. 종료 시 소비 스레드는 최대 5초 drain을 기다린다.

Worker는 PostgreSQL session advisory lock으로 F3 실행 한 건만 선점한다. 이 전용 연결은
AUTOCOMMIT이며 모델 대기 동안 열린 transaction·행 잠금을 유지하지 않는다. 다른 호스트에
Worker를 늘려도 F3 실행 슬롯은 1개다. 실행 내부의 후보 카드 생성은 최대 5개 병렬이다.
현재 단일 API의 챗봇 제한 1건과 합쳐 general 모델의 애플리케이션 요청 상한은 6건이다.
이는 GPU 처리량 실측값이 아니며 API를 여러 프로세스·호스트로 늘리려면 챗봇 admission도
공유 저장소에서 제한해야 한다.

lease는 300초, 소유자·attempt를 확인하는 별도 heartbeat는 30초 간격이다. 만료한 lease는
최대 claim 3회까지 복구하며 일시 실패 후 `5 × attempt_count`초를 기다린다. 수동 요청은
priority 100, 자동 요청은 0이고 이미 실행 중인 작업을 선점 중단하지 않는다. 새 입력과
lease 상실 시 늦은 결과는 현재 결과 포인터를 덮지 못한다. 연결 단절로 슬롯을 잃었을 때의
일시적 외부 추론 중복 가능성까지 exactly-once로 보장하지는 않는다.

별도 Worker 서버를 위한 실행 상태 경계는 준비되어 있지만 현재 배포는 API·Worker를 함께
관리한다. 실제 서버 분리는 SG/IAM·환경 주입·독립 배포·drain·관측 검증이 추가로 필요하다.
현재 단계에 SQS·추가 EC2·GPU는 필수가 아니다. 자세한 배포 근거는
[Worker 배포 검토](../../../../docs/architecture/f3/worker-deployment-review.md),
기능·API 범위는 [결과 목록 요구사항](../../../../docs/requirements/f3/judgment-results-list.md)과
[확장 계약](../../../../docs/architecture/f3/expansion-contracts.md)을 따른다.

## 이번 확장의 검증 경계

`tests/integration/test_f3_automation.py`는 실제 PostgreSQL에서 원자 이벤트·중복 접수·완료
재사용·새 후보·늦은 응답·비입력 수정·UTC 재검증·전역 슬롯을 검증한다. 기존 F3 API 회귀는
저장 요청이 실행을 직접 접수하지 않는 변경과 CARD_ONLY 승격 호환을 함께 확인한다.
`tests/unit/test_f3_worker_reliability.py`는 heartbeat fencing·종료와 독립 소비를 검증한다.

`backend/scripts/f3_browser_validation.py`는 명시 확인과 localhost의 `*_validation` DB,
합성 seed를 요구하는 재현 도구다. 실제 HTTP·outbox·Worker·PostgreSQL을 사용하지만 모델은
결정적 테스트 generator다. 제품 설정에 fake fallback을 추가하지 않는다. 실제 모델 품질과
GPU p95·장애 부하 시험은 이 성공 검증으로 대신하지 않는다.

## 이전 리팩토링 검증 기록

2026-09-09 별도 워크트리에서 잠금 파일의 Backend 의존성으로 검증했다.

- 임시 로컬 PostgreSQL 15에 Yoyo 전진 migration을 적용했다. 기존 개발 DB는 사용하지 않았다.
- `test_candidate_cards`에 첫 번째·중간 후보 실패 회귀 사례를 추가했다. 수정 전 2건 실패를
  재현했고 수정 후 성공 카드 2건 보존, 재시도 모델 호출 1회, 전체 후보 순서·상태 전이를 확인했다.
- PostgreSQL 통합·F3 API **216 passed**: `test_candidate_cards`, `test_agent_run_claim`,
  `test_anchor_position_card`, `test_candidate_selection`, `test_brokerage_judgment`,
  `test_position_card_backfill`과 `tests/api/test_f3_*.py` 5개 파일. 동시 선점·lease 회수,
  입력 변경·lease 상실 시 저장 거절, tenant 격리·공개 응답·자동 접수를 포함한다.
- 단위·아키텍처 **114 passed**: `test_worker`, `test_f3_runtime`, `test_execution_pipeline`,
  `test_execution_intake`, `test_candidate_scoring`, `test_position_card_cache_key`와
  `tests/architecture/`. 저장 실행 주차와 사용자 요청 승격 경합, 모델 불필요 단계의 무호출을 포함한다.
- Repository의 함수·자료형·상수 78개 AST를 병합한 dev 원본과 비교해 본문 보존을 확인했다.
- `uv run --locked --project backend ruff check --fix backend`, `ruff format backend` 통과.
  `backend/.venv/bin/pyright --project backend`는 오류·경고 0건이다.
- `node .github/scripts/check-skill-docs.mjs`와 `git diff --check` 통과.

실제 AI 호출은 테스트 대역으로 대체했다. 공유 dev 배포·GPU 처리량·저장 p95 및 여러 EC2의
운영 복구는 측정하지 않았으므로 이번 검증을 실환경 부하 검증으로 해석하지 않는다.


## PR #112 개인정보·무효 카드 리뷰 보완

리뷰에서 확인한 두 조건은 파일 분리 전에도 존재했다. 직접 연결 매물 로그의 당사자 검사
누락은 유효한 finding이며, 명시된 당사자가 허용 범위에 속하도록 수정했다. 당사자 미기재
직접 연결과 세대 전용 로그의 기존 차이는 유지한다. 상담 범위를 `interaction-scope:v3`로
올려 새 캐시 조회·입력 저장 검증에서 이전 범위를 재사용하지 않게 한다.

`find_anchor_card_for_run`의 무효 카드 제외 누락은 결과 조회 경로에서 유효하다. 후보 선정은
`find_position_card_for_target`, 판정 입력은 `list_position_cards`가 이미 무효 카드를 제외하므로
해당 함수 때문에 후속 판정 입력에도 무효 카드가 전달된다는 영향 설명은 맞지 않는다.
결과 조회에서는 헤더 참조를 우선하고 헤더가 없을 때만 snapshot을 사용하며, 공통 활성 조건을
적용한다. 앵커가 없으면 그 앵커에 의존한 판정·근거도 공개하지 않는다.

신규 테스트 4건으로 수정 전 실패를 재현했다. 직접 로그의 당사자·측면·무효화와 생성 요청·
source summary 일치, 헤더/snapshot의 무효 카드, 다른 유효 snapshot으로의 우회 조회를 검사한다.
기존 생성물의 일괄 삭제·무효화와 자동 최신성 판단은 이 수정에 포함하지 않는다.

병렬 처리 지적의 제외는 타당하다. 병합 기준 dev 코드도 이미 `asyncio.gather`로 생성했고
이번 PR은 성공 카드 보존과 오래된 순차 생성 설명을 수정했다. 문서에 `결정`이라고 표기하거나
같은 PR에서 문장을 바꾸는 것만으로 새 정책의 팀 승인이 성립하는 것은 아니다.

리뷰 수정 후 `test_anchor_position_card`, `test_candidate_selection`, `test_brokerage_judgment`,
`test_f3_results`, `test_position_card_cache_key`와 `tests/architecture/`를 실행해 **126 passed**를
확인했다. Ruff·Pyright·스킬 문서 검사도 통과했다. 실제 외부 AI 호출은 실행하지 않았다.
