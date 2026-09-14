---
status: 구현됨
updated: 2026-09-10
---

# F3 실행 경계와 확장

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

`execution_policy`는 실행 권한이나 자동 판정 조건을 승인하는 모듈이 아니다. 저장으로 생성된
실행은 기존 [ADR-0018](../../project-wiki/references/decisions/ADR-0018-f3-save-trigger-anchor-card-scope.md)에
따라 앵커 카드 이후 대기한다. 사용자 요청과 겹칠 때는 여전히 `park_ledger_save_run`의 조건부
UPDATE 결과로 승격 여부를 확인한다. 메모리에서 선택한 단계만 믿고 상태를 바꾸지 않는다.

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

## 서버 분리와 다음 확장

API와 Worker는 동일 image를 쓰는 별도 프로세스·컨테이너다. 같은 EC2 배치는 초기 dev에
사용할 수 있으며, 작업 분배·재개는 프로세스 메모리 대신 PostgreSQL이 소유한다.
이번 분리는 DB 기반 소비자를 다른 호스트에 배치하는 기존 경계를 유지한다.
다만 다중 호스트 배포가 구현 완료됐다는 뜻은 아니다. 현재 공용 EC2와 배포 스크립트는
API·Worker를 함께 관리하며 독립 확장에는 SG/IAM·환경 주입·배포 검증과 GPU 동시성 관리가 필요하다.
자세한 근거는 [Worker 배포 검토](../../../../docs/architecture/f3/worker-deployment-review.md)에 있다.

2026-09-10 사용자 승인 개선에서 단계별 30초 heartbeat를 추가했다. 300초 lease·최대 claim 3회와
DB fencing은 유지하며 [ADR-0006](decisions/ADR-0006-f3-lease-renewal.md)이 갱신·취소 경계의 정본이다.
Worker 수·대기열 우선순위와 Provider 전체 동시성 제한은 변경하지 않았다.

새 조건부 자동 판정·완료 결과 재사용·결과 목록·독립 카드 API는 이 리팩토링에 포함되지 않는다.
제품 기준은 [조건부 자동 판정 제안](../../../../docs/architecture/f3/conditional-auto-judgment.md)과
[결과 목록 요구안](../../../../docs/requirements/f3/judgment-results-list.md)에 있다.
추후 자동 접수 정책은 `triggers`/`service`, 최신성·무효화는 입력 revision과 결과 조회,
영속 이벤트는 F1 commit 경계에서 구현한다. 상태→단계 매핑에 모든 정책을 섞지 않는다.

## 검증 기록

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


## 조회·계측 개선 (2026-09-10)

결과 조회는 같은 run·판정 헤더를 재사용해 전체 JSONB snapshot 중복 조회를 제거한다.
기존 유효 후보 판별·총건수·SQL 순서를 유지하며 현재 페이지의 View·판정·근거만 조립한다.
매물 후보 SQL은 필요한 컬럼만 projection한다. 전체 snapshot 한 번 읽기와 후보 목록 순회는 남는다.

`f3_timing`은 접수·상태·결과·Worker 단계의 run_id, wall_ms, sql_count/sql_ms를 남긴다.
SQL 시간은 cursor 실행 시간이며 JSON 역직렬화·ORM 조립·응답 검증은 wall 시간에 포함된다.
`f3_card_cache`는 후보 카드 hit/miss, `f3_model_call`은 공개 Provider port의 생성 task별
호출 순번·시간·성공 여부를 기록한다. 같은 task의 후속 provider_attempt는 AI 내부 repair 호출이며
새 Worker attempt와 구분한다. 요청·SQL·파라미터·상담·모델 원문은 기록하지 않는다.
병렬 호출 시간의 합계는 처리 지연이 아니므로 stage wall_ms와 별도로 해석한다.

측정 및 남은 병목은 [검증 보고서](../../../../docs/validation/f3-reliability-performance-2026-09-10.md)에 둔다.


범용 vLLM의 스트리밍 도입에 따라 Worker는 SDK client를 닫은 다음
`loop.shutdown_asyncgens()`를 완료하고 event loop를 닫는다. 스트림 내부 비동기 generator의
정리 작업을 버리지 않도록 벤치마크도 같은 종료 순서를 사용한다. Provider 내부 로컬 대기는
`f3_model_call.wall_ms`에 포함되고 Provider diagnostics 시간에는 포함되지 않는다.
범용 300초 설정과 실제 RunPod 시드 측정은
[RunPod 검증 보고서](../../../../docs/validation/f3-runpod-performance-2026-09-10.md)를 따른다.
