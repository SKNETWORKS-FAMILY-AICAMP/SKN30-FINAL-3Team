---
status: 구현됨
updated: 2026-09-08
implementation: 코드 구현·로컬 PostgreSQL 검증, 공유 dev 미적용
---

# F4 챗봇 저장·실행 수명주기 설계

[사용자 설계 합의](../../requirements/sources/chatbot-design-decisions-2026-09-08.md)를 구현하기 위한 논리 설계다.
제품 범위는 [요구사항](../../requirements/chatbot/overview-and-scope.md), 전송 계약은 [HTTP·SSE 설계](api-and-stream.md), 보존 정본은 [개인정보 정책](../../../.agents/skills/project-wiki/references/privacy/policy.md)의 F4 챗봇 절이다.
구체 SQL은 [019_CREATE_CHATBOT](../../db/migrate/019_CREATE_CHATBOT.sql)이 정본이다. 격리된 로컬 PostgreSQL에서 검증하며 기존 migration과 업무 데이터는 변경하지 않는다. 공유 dev 적용은 별도 배포 작업이다.

## 최소 테이블 3종

| 테이블 | 소유 데이터 | 주요 컬럼 |
|---|---|---|
| `chat_conversation` | 사용자별 현재 대화 1개·현재 검색 조건 | `id`, `brokerage_id`, `owner_user_id`, `active_filters`, `state_version`, `created_at`, `updated_at` |
| `chat_request` | 사용자 질문 한 건의 처리·중복 접수·최종 상태 | `id`, `brokerage_id`, `conversation_id`, `client_request_id`, `request_fingerprint`, `status`, `stage`, `revision`, `context_snapshot`, `owner_instance_id`, `heartbeat_at`, `deadline_at`, `started_at`, `completed_at`, `failure_code` |
| `chat_message` | 사용자에게 보이는 질문·답변과 결과 카드 | `id`, `brokerage_id`, `conversation_id`, `request_id`, `sequence_no`, `role`, `content`, `payload_version`, `result_payload`, `created_at` |

질문·답변 모두 같은 request에 연결한다. request가 message를 다시 FK로 참조하지 않도록 해 삽입 순환을 피한다.
`result_payload`는 표시한 최소 결과 카드·조회 조건·총건수·출처 참조·기준 시각을 저장한다. 조회 전체 행·연락처·상담 원문·모델 내부 추론을 무제한 복제하지 않는다.
`context_snapshot`은 요청 시 서버가 확정한 조건·참고 메시지 ID 등 실행 입력의 최소 문맥이다. 전체 prompt나 인증정보를 저장하지 않는다.
필요한 모델·프롬프트 버전·토큰 수·지연은 request의 제한된 진단 필드로 추가할 수 있다. 결과 본문과 관측 로그를 구분한다.
기간 만료·자동 아카이브·다중 대화 제목·벡터·첨부파일·메시지 분기용 컬럼은 1차에 만들지 않는다.

## 관계·제약·조회

- conversation의 `(brokerage_id, owner_user_id)`를 UNIQUE로 두어 사용자당 1개를 보장한다. 전체 삭제 후 다음 질문에서 새 ID로 다시 만든다.
- 기존 DB처럼 `(brokerage_id, id)` 복합 키와 FK를 사용한다. message→request는 conversation까지 같은지 검증하는 복합 FK를 설계해 다른 대화의 request가 섞이지 않게 한다.
- 애플리케이션은 사무소와 `owner_user_id`를 모두 검사한다. 사무소 관리자 역할만으로 다른 사용자의 챗 이력을 열지 않는다. DB 운영자 권한은 제품 조회 권한과 별도다.
- message 순서는 `(conversation_id, sequence_no)` UNIQUE로 보장하고 conversation을 짧게 잠가 순번을 할당한다. LLM 호출 중 트랜잭션을 유지하지 않는다.
- 요청 중복 키는 `(conversation_id, client_request_id)` UNIQUE다. 같은 키·같은 fingerprint는 기존 request 반환, 같은 키·다른 입력은 충돌로 거절한다.
- `(conversation_id, role, request_id)` 제약 등으로 request당 질문 1개·완료 답변 최대 1개를 보장한다. 실패는 request 상태로 표시하고 가짜 정상 답변을 저장하지 않는다.
- 대화별 활성 요청은 최대 1개다. 부분 UNIQUE와 짧은 트랜잭션으로 여러 탭의 동시 질문을 거절한다. 이 제한은 범용 GPU 전체 동시성 제한을 대체하지 않는다.
- 이력은 순번 cursor로 페이지 조회하며 전체 대화를 한 번에 내려주지 않는다. 현재 필터·상태는 버전으로 관리하고 오래된 탭의 변경은 충돌 안내한다.

## 요청 상태와 영속화 순서

구현 상태: `ACCEPTED → RUNNING → COMPLETED | FAILED | CANCELLED | INTERRUPTED`. 접수 직후 취소·중단은 `ACCEPTED`에서도 terminal 상태로 이동한다.
추가 질문이 필요한 경우에도 답변 형태가 `clarification`인 `COMPLETED`로 종료한다. 모델 문맥의 1회는 이처럼 완료된 사용자 질문·응답 한 쌍이다.

1. 인증·CSRF·입력·GPU 수용 가능 여부를 확인한다. 서비스 불가/혼잡은 장시간 큐에 넣지 않고 503/429로 반환한다.
2. conversation 버전·활성 요청을 검사하고 request(`ACCEPTED`)와 사용자 message를 같은 트랜잭션에 저장한다.
3. commit 후 Backend가 소유한 실행 task를 등록한다. SSE 연결과 실행 task의 수명을 분리하고 요청별 실행 소유자를 기록한다.
4. 단계·heartbeat를 짧은 갱신으로 저장한다. 완료 시 답변 message, 최신 필터, request 완료 상태·revision을 같은 트랜잭션에 commit한다.
5. SSE는 commit된 상태만 알린다. 연결이 끊겨도 결과는 DB에서 읽을 수 있다. 모델이 끝났더라도 DB 저장이 실패하면 완료라고 알리지 않는다.

초기에는 기존 단일 Backend 프로세스의 task 관리로 구현할 수 있다. FastAPI 응답 후 작업 하나만 등록하고 완료를 보장한다고 가정하지 말고 task 참조·예외·shutdown·deadline을 명시 관리한다.
접수 commit과 task 등록 사이의 서버 중단은 복구 대상이다. 초기 기동 또는 주기적 상태 정리에서 이전 소유자·기한이 지난 활성 요청을 `INTERRUPTED`로 전환한다.
상태 정리는 모델을 재실행하지 않는다. 중단 판정과 실제 완료가 경합하면 조건부 상태 갱신으로 먼저 확정된 terminal 상태를 보존한다.
서버가 살아 있는 동안 탭 종료·새로고침은 실행을 취소하지 않는다. 서버 재시작 후 자동 재실행은 제공하지 않으며 사용자가 새 요청으로 재시도한다.

## 취소와 전체 삭제

- 명시적 중지는 request를 `CANCELLED`로 바꾸고 후속 호출을 막는다. 이미 실행 중인 원격 추론은 즉시 끝나지 않을 수 있어 실제 자원 종료 전 수용 슬롯을 함부로 반환하지 않는다.
- 완료 갱신은 `RUNNING`이며 conversation이 여전히 존재하는 경우에만 허용한다. 취소가 먼저 반영되면 늦은 모델 결과를 저장하지 않는다.
- 전체 삭제는 conversation과 소속 message·request를 단일 트랜잭션으로 물리 삭제하고 성공 후 204로 응답한다. 소프트 삭제와 24시간 삭제 배치는 사용하지 않는다.
- 삭제와 접수/완료는 동일 conversation의 잠금·FK로 직렬화한다. commit 전 실패하면 삭제 성공으로 표시하지 않는다.
- 실행 중 삭제되면 실행 task에 취소를 알리고 이후 저장은 conversation 부재로 거절한다. 완료 callback은 삭제된 대화를 upsert하거나 자동 재생성하지 않는다.
- 프론트는 삭제된 conversation ID의 늦은 이벤트를 폐기한다. 다른 탭의 오래된 ID로 보낸 질문은 404/충돌로 거절하고 새 대화를 자동으로 만들지 않는다.
- 데이터는 사용자 삭제 또는 시연 환경 폐기까지 보존한다. 운영 DB 삭제와 백업·Provider의 보존을 구분하며 환경 종료 때 기존 정책에 따라 별도 정리한다.

## 문맥과 확장 경계

Backend가 DB에서 직전 완료 2회와 현재 검색 조건을 선택한다. 클라이언트가 과거 답변을 보내 권위 있는 이력으로 쓰게 하지 않는다.
실패·취소·중단 질문은 기본 문맥에서 제외한다. 토큰 상한을 넘으면 입력 축약을 안내하고 무제한 오래된 대화 요약·장기 기억을 자동 생성하지 않는다.
이전 답변 카드는 당시 기록이며 현재 장부와 다를 수 있다. 이력에는 기준 시각을 표시하고 상세 열기·후속 질문은 대상 존재·권한·현재값을 다시 확인한다.

향후 F3 연동 시 request와 기존 `agent_run` 사이의 연결 테이블을 별도로 검토한다. 챗봇 삭제가 F3 감사 이력을 cascade 삭제하지 않도록 연결만 끊는 수명주기를 둔다.
도구 호출 상세, SSE 이벤트 재생, 작업 재개용 checkpoint, 첨부파일, 여러 대화방은 실제 기능 착수 때 추가한다. 현재 설계는 이들을 이미 구현한 것으로 취급하지 않는다.

## 구현 검증 기준

- 타 사용자·타 사무소 접근 거부, 동일 사용자 공용 dev 계정 한계 표시, 복합 FK 범위 검증.
- 동일 키 동시 접수와 변경 입력 충돌, 여러 탭 활성 요청 제한, 순번 안정성.
- 접수 직후·모델 실행 중·완료 commit 전 서버 중단, SSE 연결 종료, 새로고침 후 DB 상태 복원.
- 완료/취소/삭제의 경합에서 답변 중복과 삭제한 대화의 재생성 0건.
- 전체 삭제의 트랜잭션 원자성, 운영 DB 잔여 데이터, 오래된 탭과 늦은 이벤트 무효화.
- 전진 migration `019_CREATE_CHATBOT`의 적용·rollback·재적용과 복합 FK를 격리된 PostgreSQL에서 검증한다.

구현은 요청에 `search_filters`와 안전한 `diagnostics` JSONB도 저장한다. 모델·workflow·prompt 버전, 호출 횟수·토큰·지연을 기록하며 원시 prompt·모델 응답은 보관하지 않는다.
