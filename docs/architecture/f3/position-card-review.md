---
status: 제안
updated: 2026-09-09
---

# F3 구현 현황과 포지션 카드 분리 검토

최초 검토는 2026-09-09 로컬 `dev`의 `174903a` 기준이다. 후속 리팩토링은 최신 `dev`
`1d44019`를 병합한 뒤 진행했다. [리팩토링 구현·확장 경계](../../../.agents/skills/backend/references/f3-execution.md)를 함께 본다.
공유 dev의 현재 배포 revision·DB·실제 요청 지연은 조회하지 않았다. 아래 구현 사실은 코드 기준이며 성능 수치는 실측값이 아니다.

## 최신 구현 진입

최신 dev `f700f5a`를 병합해 구현한 1차 범위는 [기능 정의](../../requirements/f3/judgment-results-list.md),
[화면 위치·이동](../../screen/f3-judgment-results.md), [조회 API·내부 확장](expansion-contracts.md)에 둔다.
[페르소나 검토·검증안](planning-validation.md)과 [챗봇 후속 연계](chatbot-extension.md)를 반영했다. **현재 코드·검증은 [1차 구현 기록](implementation-and-validation.md)과 [ADR-0035](../../../.agents/skills/project-wiki/references/decisions/ADR-0035-f3-conditional-automation-results.md)가 우선한다.**
아래는 당시 코드의 역사적 검토이며 현재 Worker heartbeat·자동 실행·완료 재사용 정책과 다르다. 과거 검증을 이번 검증으로 재집계하지 않는다.

## 검토 결론

후속 사용자 요청을 반영해 제품·자동 실행 권고를 수정했다. [Worker 실행·확장성](worker-deployment-review.md),
[상시 GPU·조건부 자동 판정](conditional-auto-judgment.md), [결과 목록 요구안](../../requirements/f3/judgment-results-list.md)이 최신 검토다.

- 포지션 카드 생성과 교차 판정은 이미 HTTP 요청에서 분리된 DB 작업·Worker 방식이다.
- 저장 요청에는 F3 접수용 DB 작업이 남아 있다. 이벤트 분리의 추가 효과는 접수 비용 축소와 작업 누락 복구다.
- 교차 판정은 결과를 이미 저장한다. 호출 절감의 핵심은 **완료 결과의 유효성 검증과 재사용**이다.
- 초기 독립 카드 요청은 [대안 요구안](../../requirements/f3/position-card-delivery.md)에 보존한다. 최신 권고는 조건부 자동 판정의 결과 목록을 우선하고 카드는 근거 상세로 제공하는 것이다.
- [이벤트·재사용 설계](position-card-events.md), [로컬·dev 자원 제안](position-card-infrastructure.md)을 단계적으로 적용하는 안을 권고한다. 아직 구현·승인한 변경은 아니다.

## 최초 검토 당시 구현

| 흐름 | 코드에서 확인한 동작 | 근거 |
|---|---|---|
| 장부 저장 | F1 commit 후 같은 HTTP handler에서 F3 접수, 그 뒤 응답 | [property_ledger.py](../../../backend/src/api/property_ledger.py), [F1 service](../../../backend/src/domain/property_ledger/service.py) |
| 자동 접수 | 신규 또는 관련 필드의 실제 변경만 `LEDGER_SAVE` 접수. 메모·담당자 변경, 같은 값 재저장은 제외 | [triggers.py](../../../backend/src/domain/agent_execution/triggers.py) |
| 접수 DB 작업 | 사무소·앵커 advisory lock → 권한·버전 조회 → 활성 실행 조회 → insert 또는 재사용 → commit | [service.py](../../../backend/src/domain/agent_execution/service.py), [repository/runs.py](../../../backend/src/domain/agent_execution/repository/runs.py) |
| 카드 선생성 | Worker가 앵커 카드를 확보하고 `ANCHOR_READY`에서 대기. 사용자의 판정 요청이 같은 실행을 이어받음 | [pipeline.py](../../../backend/src/domain/agent_execution/pipeline.py), [ADR-0018](../../../.agents/skills/project-wiki/references/decisions/ADR-0018-f3-save-trigger-anchor-card-scope.md) |
| Worker | 빈 큐는 2초 polling, 프로세스당 실행 1건 처리. DB lease 300초·최대 claim 3회, heartbeat 없음 | [worker.py](../../../backend/src/worker.py), [service.py](../../../backend/src/domain/agent_execution/service.py) |
| 카드 캐시 | `position-card:v3`: 입력 전체 지문·상담 범위·대상 버전·모델·prompt·workflow 포함. UTC 날짜 bucket 포함 | [anchor_card.py](../../../backend/src/domain/agent_execution/anchor_card.py), [fingerprint.py](../../../backend/src/domain/agent_execution/fingerprint.py) |
| 후보·판정 | SQL 후보 선정 → 상위 5건 카드 cache miss 병렬 생성 → 앵커 1장과 후보 최대 5장으로 한 번의 논리적 판정 | [candidate_cards.py](../../../backend/src/domain/agent_execution/candidate_cards.py), [judgment.py](../../../backend/src/domain/agent_execution/judgment.py) |
| 영속 결과 | 카드·가격·근거는 `negotiation_position_*`, 후보 snapshot·판정·근거는 `match_*`, 상태는 `agent_run` | [models.py](../../../backend/src/domain/agent_execution/models.py) |
| 조회 API | `GET /api/v1/f3/runs/{run_id}` 및 `/result`는 저장 데이터 조회. 모델 호출 없음. `/result`에 앵커 카드 포함 | [f3_runs.py](../../../backend/src/api/f3_runs.py), [results.py](../../../backend/src/domain/agent_execution/results.py) |
| 실행 재사용 | `POST /api/v1/f3/runs`는 같은 앵커·row_version의 활성 실행만 재사용. `COMPLETED`는 새 실행 | [service.py](../../../backend/src/domain/agent_execution/service.py) |
| 화면 재사용 | 같은 브라우저 메모리에 실행 ID를 보관. 패널 재열기·페이지 이동은 재조회, 새로고침·명시적 retry는 새 POST 가능 | [useCrossJudgment.ts](../../../frontend/src/features/f3/hooks/useCrossJudgment.ts) |
| 기존 데이터 준비 | 앵커 카드 backfill과 coverage 도구 존재. 활성 실행 재사용이므로 최신성 보장·자동 누락 복구와 동일하지 않음 | [backfill.py](../../../backend/src/domain/agent_execution/backfill.py) |

후속 리팩토링에서 런타임 문서와 AI 계약의 후보 생성 설명을 실제 병렬 구현에 맞췄다.
코드 주석의 과거 속도 측정값을 현재 환경의 성능으로 인용하지 않는다.

## 저장 시 부하

저장 응답 시간은 대략 `F1 저장 + F3 접수 DB 시간 + 응답 조립`이다. AI 생성 시간은 여기에 들어가지 않는다.
F3 접수는 같은 요청에서 실행되므로, 코드의 “비차단”은 **AI를 기다리지 않는다**는 의미다.
같은 앵커의 접수가 겹치면 `pg_advisory_xact_lock`을 기다리고, DB 연결·조회·추가 commit 비용도 있다.
접수 경로에 별도 lock/statement timeout 설정은 확인되지 않았다. 실제 서버 기본값과 지연은 미확인이다.

F1 commit 뒤 프로세스가 중단되거나 F3 접수가 실패하면 장부만 저장될 수 있다.
예외를 삼켜 F1 성공을 유지하지만 실패 로그 외에 자동 재접수 보장은 없다.
Worker의 모델 호출 전후 transaction 분리는 이미 구현돼 있어 모델 대기 동안 DB transaction을 붙잡지 않는다.

백그라운드 비용은 남는다. 카드 입력은 허용된 측면의 상담 로그 전체를 읽으므로 이력이 많을수록 조회·토큰 비용이 증가한다.
연속 수정이 Worker 실행과 겹치면 오래된 입력에 모델을 쓴 뒤 저장 시 폐기할 수 있다.
다른 실행들이 같은 후보 카드 cache miss를 동시에 발견하면 저장 중복 방지는 있어도 모델 호출 중복은 가능하다.

## 교차 판정의 반복 비용

정상 성공·repair 없는 경로에서 모델 호출 수는 다음과 같다.

| 상황 | 모델 호출 수 |
|---|---|
| 저장으로 앵커 카드 확보 | 캐시 hit 0회, miss 1회 |
| 후보 1~5건의 신규 판정 | 앵커 miss 0~1 + 후보 miss 0~5 + 판정 1 = 1~7회 |
| 카드가 전부 유효한 상태에서 완료 후 새 POST | 카드 0 + 판정 1회 |
| 상태·결과 GET 또는 메모리에 남은 실행 재조회 | 0회 |
| 후보 0건 | 후보 카드·판정 0회. 앵커가 없으면 앵커 생성은 필요 |

[구조화 출력 repair](../../../ai/src/brokerage_ai/providers/repair.py)는 생성당 원본 포함 최대 3회다.
Worker 재시도·lease 만료까지 겹치면 호출이 더 늘 수 있으므로 위 표를 절대 상한으로 해석하면 안 된다.
최초 검토에서 앞 후보 실패 시 뒤의 성공 카드까지 저장하지 않는 버그를 확인했다.
후속 리팩토링에서 개별 성공 카드를 저장하고 재시도 시 재사용하도록 수정했다.
서로 다른 실행의 동일 카드 동시 생성 방지는 여전히 후속 절감 지점이다.

## 최신성의 공백

- 자동 접수 연결은 매물·구입장 create/update 4곳이다. 상담 로그·세대·단지·관계 변경까지 포괄하는 이벤트 연결은 없다.
- `invalidated_at` 조회 조건은 있으나 Backend 코드에서 관련 입력 변경 시 이를 갱신하는 경로는 확인되지 않았다. 카드 생성 경로의 fingerprint 검증과 자동 무효화는 구분해야 한다.
- 활성 실행 재사용은 row_version만 본다. 오래 대기한 `ANCHOR_READY`는 상담·연관 정보·날짜·모델 변경을 접수 시 검증하지 않는다.
- 현재 `/result`는 과거 실행 snapshot 조회다. 반환 전에 전체 최신 입력을 다시 계산하는 API가 아니다. 단순히 “최신 완료 행”을 읽는 방식으로 확장하면 오래된 결과를 최신으로 표시할 수 있다.
- 최종 순위는 후보 집합 전체에 의존한다. 기존 후보 수정뿐 아니라 **새 상대 후보 등록·삭제·조건 진입**도 재사용 무효화에 포함해야 한다.

## 최초 검토의 검증 범위

별도 워크트리에서 기존 `test_execution_intake`, `test_execution_pipeline`, `test_position_card_cache_key`, `test_worker` 4개 단위 테스트 파일을 실행해 **86 passed**를 확인했다.
명령: 기존 Backend 가상환경의 Python으로 `python -m pytest backend/tests/unit/test_execution_intake.py backend/tests/unit/test_execution_pipeline.py backend/tests/unit/test_position_card_cache_key.py backend/tests/unit/test_worker.py -q`.
API까지 포함한 최초 실행은 DB 관련 skip과 장시간 정체 후 중단했으므로 API·DB 통합 검증 통과로 집계하지 않는다.
검토 문서의 상대 링크와 `git diff --check`도 확인했다. 최초 검토 단계에서는 런타임 코드를 변경하지 않았다. 후속 구현과 검증은 위 리팩토링 문서에 기록한다.
실제 DB 잠금 경합·저장 p95·GPU 지연·처리량은 이번 코드 검토에서 측정하지 않았다.
측정 절차와 구현 수용 시나리오는 [자원·검증 제안](position-card-infrastructure.md)에 둔다.
