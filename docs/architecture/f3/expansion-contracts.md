---
status: 구현됨
updated: 2026-09-09
---

# F3 확장 API와 내부 기능

최신 dev `f700f5a` 병합 후 1차 구현 상태다. [기능 정본](../../requirements/f3/judgment-results-list.md)의 사용자 승인 범위를 구현했다. 공개 HTTP 필드·오류는 [조회 계약](../../../.agents/skills/project-wiki/references/contracts/api-f3-judgments.md), 기존 접수·실행은 [F3 계약](../../../.agents/skills/project-wiki/references/contracts/api-f3.md)이 정본이다.

## 화면과 HTTP

| 화면/동작 | API (`/api/v1` 아래) | 실행 의미 |
|---|---|---|
| 공통 교차 판정 목록 | GET `/f3/judgment-results` | 양쪽 기준·필터·정렬·페이지. 작업/모델 호출 없음 |
| 양쪽 장부 상세 요약 | GET `/f3/judgment-targets/{anchor_type}/{anchor_id}` | 미생성도 안전한 200. 최신성·적격성·진행 상태 |
| 결과 Drawer·선택 후보 | GET `/f3/judgment-results/{result_id}` | 후보 페이지·양측 카드·근거·최근 기록 |
| 최신 분석 요청 | POST `/f3/runs` | 동일 입력의 완료/진행 실행 재사용, 필요할 때만 접수 |
| 진행 상태 | GET `/f3/runs/{run_id}` | 완료 후 대상/결과를 다시 조회 |
| 기존 클라이언트 | GET `/f3/runs/{run_id}/result` | 기존 snapshot 계약 유지. 현재성은 새 GET으로 확인 |
| 관심없음 | POST `/f3/feedback` | 기존 후보 판정 ID에 기록. 영구 제외·처리 완료 의미 없음 |
| 상담 원본 | GET `/client-interactions` + 대상 scope + `interaction_id` | 현재 존재·사무소·부모·삭제 여부를 확인한 정확한 원본 |

독립 카드 메뉴·카드 생성 API·새 `/judgment-jobs`·임의 prompt·강제 재판정 옵션은 추가하지 않았다. `result_id`는 기존 `match_evaluation.id`다. 별도 작업/결과 ID 체계도 만들지 않았다.

## 모듈별 확장

| 소유 | 구현 경로/책임 |
|---|---|
| Backend 접수 | `service.py`, `freshness.py`: 적격성·전체 의미 입력 identity·진행/완료 재사용 |
| Backend 자동화 | `automation.py`: outbox 소비·반대편 새 후보까지 보수적 fanout·변경 병합·UTC/설정 sweep |
| Backend 조회 | `judgment_queries.py`, `judgment_targets.py`, `judgment_content.py`: 안전한 목록/대상/불변 결과 snapshot 조회 |
| Backend 실행 | `worker.py`, `f3_worker_reliability.py`: DB 슬롯·선점·lease 갱신·재시도·사용자 우선순위 |
| Backend 모델 단계 | `pipeline.py`, `judgment_cache.py`: 최종 게시 fencing·같은 최종 AI 입력 재사용 |
| AI | 기존 공개 카드/판정 generator와 DTO 유지. 목록 기능용 추론·DB 의존성 추가 없음 |
| Frontend | `features/f3/judgments/`: GET 중심 목록/Drawer·양쪽 장부 연결·조회/POST 훅 분리 |
| Infra | 기존 API/Worker 프로세스·PostgreSQL·general 모델 연결 유지. 자동 활성화/병합/배치 설정만 추가 |

## 영속 상태와 처리 순서

[Migration 020](../../db/migrate/020_CREATE_F3_AUTOMATION.sql)이 자동화 상태를 추가하고 [021](../../db/migrate/021_ALTER_MATCH_AUTOMATION_NAMES.sql)이 매칭 도메인 이름으로 변경한다. 현재 객체명과 책임은 다음과 같다.

- `match_source_revision`: 사무소 단위 변경 revision. 소비 전에도 이전 결과를 stale로 판단한다.
- `match_change_outbox`: 사무소당 최신 revision·원천 테이블/ID·시각만 병합한다. 각 저장의 원문이나 일반 메시지 봉투를 보관하지 않는다.
- `match_target_state`: 대상별 desired/verified revision·검증 identity/날짜·현재 성공 run/result·due_at·의미 있는 변경 시각. 결과 정본을 복제하지 않는다.
- `agent_run.priority`, `next_attempt_at`: 사용자 우선 선점과 내구성 있는 재시도 시각.

`F1 저장 + trigger/outbox 원자 기록 → Worker 소비 → 적격성/변경 병합 → 카드·SQL 후보·최초 상위 5건 판정 → 최종 입력/lease 검증 → 결과와 최신 포인터 원자 게시 → GET` 순서다.

입력과 최종 모델 구성이 같으면 완료 결과 또는 최종 AI 출력을 재사용한다. 후보 집합 변경은 검증하되 실제 상위 5건 판정 입력이 같으면 최종 AI 호출을 줄인다. 후보 0건이면 최종 판정을 호출하지 않는다. 비입력 메모/담당자/row_version 변경은 재추론 사유가 아니다.

## 경계와 확장성

원자 기록 실패 시 원장 저장도 rollback한다. [ADR-0035](../../../.agents/skills/project-wiki/references/decisions/ADR-0035-f3-conditional-automation-results.md)가 기존 commit 후 접수 실패 무시와 카드까지만 자동 생성하던 ADR-0018을 부분 대체한다.
자동 flag가 꺼져도 이벤트와 조회·수동 접수는 남는다. 켜진 Worker의 maintenance 소비는 모델 대기와 별도 스레드/DB 세션으로 동작한다. API와 Worker는 별도 프로세스이며 서로의 스레드가 아니다.

같은 PostgreSQL에 연결한 여러 Worker는 공유 실행 슬롯·lease를 사용한다. 독립 EC2로 이동할 때 도메인/API를 다시 나눌 필요는 없지만 배포 단위·권한·네트워크·관측은 별도로 준비해야 한다. 전역 F3 슬롯은 현재 1개로 제한하므로 Worker 수를 늘리는 것만으로 모델 처리량이 늘지는 않는다.

목록은 사무소의 최소 표시정보와 최신 실행 snapshot을 묶어 조회한 뒤 서버에서 필터·페이지를 구성한다. 브라우저 장부 전수 로딩과 행별 N+1은 피했지만 DB `LIMIT` 중심의 대규모 집계 projection은 아니다. 단건 대상/결과는 해당 대상과 후보 ID로 제한한다. 대형 사무소의 목록 지연·DB 메모리는 실측 후 집계/인덱스 확장을 검토한다.

후속 챗봇은 같은 Backend 조회/접수 함수를 adapter로 재사용한다. 현재는 F3 도구를 활성화하지 않으며 대화 삭제/취소와 사무소 공유 작업의 수명을 분리한다. [챗봇 연계](chatbot-extension.md)의 후속 검증 항목은 유지한다.

보존/개인정보는 [정책](../../../.agents/skills/project-wiki/references/privacy/policy.md)을 따른다. 실제 검증·운영 설정·한계는 [구현 기록](implementation-and-validation.md)에 둔다.
