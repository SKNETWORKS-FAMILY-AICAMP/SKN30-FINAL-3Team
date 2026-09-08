---
status: 구현됨
updated: 2026-09-08
implementation: 코드 구현·로컬 검증, 공유 dev 미배포
---

# F4 챗봇 HTTP·SSE·복구 설계

[사용자 합의](../../requirements/sources/chatbot-design-decisions-2026-09-08.md)에 따라 기존 메모리 전용 POST 스트림 제안을 대체한다.
저장·소유권·상태의 논리 설계는 [저장 설계](persistence.md), 실제 공개 계약의 진입점은 [공통 API 계약](../../../.agents/skills/project-wiki/references/contracts/api.md)이다.
아래 경로는 구현한 v1 계약이다. [구현·검증](implementation-and-validation.md)에 로컬 실행법과 실제 평가 범위를 기록한다. 공유 dev에는 미적용이다.

## 실행 생성과 구독 분리

`POST 요청 접수 → 202와 request ID → GET 상태/SSE 구독` 흐름으로 설계한다.
사용자 메시지와 실행 상태를 commit한 후 Backend 소유 task를 실행한다. SSE 연결은 실행 시작·취소의 조건이 아니다.
새로고침·탭 종료 뒤에도 서버 task가 살아 있으면 계속 처리하고 완료 결과를 저장한다. 서버 중단 시 자동 재실행하지 않는다.

| Method·경로 (공통 접두어 `/api/v1/chatbot`) | 책임 |
|---|---|
| GET `/conversation` | 현재 사용자의 대화 1개·현재 조건·활성 요청 조회. 없으면 비어 있는 상태 |
| POST `/conversations` | 명시적 첫 질문 흐름에서 사용자 대화를 생성. 동시 생성은 사용자 UNIQUE로 기존 1개 반환 |
| GET `/conversations/{id}/messages` | 작성자 소유 대화의 이력을 cursor로 페이지 조회 |
| POST `/conversations/{id}/requests` | 질문·문맥 기준 버전·`client_request_id` 검증 후 실행 접수, 202 응답 |
| GET `/requests/{id}` | DB의 최신 단계·terminal 상태·최종 답변 참조/결과 조회 |
| GET `/requests/{id}/events` | 최신 스냅샷으로 시작하는 SSE 구독. 지나간 이벤트 재생 없음 |
| POST `/requests/{id}/cancel` | 명시적 중지. 조건부 상태 전이·원격 취소 시도 |
| PATCH `/conversations/{id}/filters` | `expected_version`을 검사하고 현재 검색 조건만 초기화. 활성 요청·버전 충돌은 409 |
| GET `/requests/{id}/results?offset=10` | 저장된 조건으로 권한을 재검증해 현재 결과·총계·기준 시각 반환. 대화 이력 변경 없음 |
| DELETE `/conversations/{id}` | 대화·메시지·요청 기록을 운영 DB에서 원자적으로 즉시 삭제 |

모든 경로는 세션의 사무소와 대화 작성자를 검사한다. 변경 요청은 기존 Cookie 세션·`X-CSRF-Token`을 사용한다.
권한 없는 ID와 없는 ID를 구분해 내부 정보를 노출하지 않는다. 현재 dev 공용 합성 계정은 서로 다른 실제 사람을 구분하지 못한다.
이력·상태·SSE·생성 응답은 `Cache-Control: no-store`를 적용한다.

## 질문 입력과 중복 접수

요청 본문은 현재 질문, 화면의 명시 선택 대상, 현재 조건의 예상 버전, `client_request_id`만 받는 안이다.
과거 이력은 Backend가 DB에서 직전 완료 2회를 선택한다. 클라이언트 `history`를 권위 있는 이력으로 받지 않는다.
현재 조건은 서버 저장값을 기준으로 하며 클라이언트의 조건 변경 요청은 전체 재검증한다. 오래된 버전은 충돌 안내한다.

- 같은 대화·같은 중복 키·같은 입력이면 기존 request ID를 반환하고 다시 실행하지 않는다.
- 같은 키에 다른 입력은 409로 거절한다. 실패한 요청을 사용자가 재시도하면 새 키·새 request를 만들고 이전 실패 이력은 보존한다.
- 대화별 진행 요청은 1개로 제한한다. 여러 탭의 다른 질문은 기존 진행 요청을 안내하고 동시에 받지 않는다.
- 범용 GPU가 혼잡하면 큐를 무한히 쌓지 않고 429, 꺼져 있으면 503으로 안내한다. 챗봇 제한만으로 F3와 공유하는 GPU 경합이 해결되지는 않는다.

## SSE 상태 전달

공통 봉투는 `schema_version`, `request_id`, `revision`, `occurred_at`, `type`, `payload`다.
payload는 최신 Request 응답이며 `search_filters`에 Backend가 검증한 검색 출처·조건을 담는다. revision은 DB 상태의 단조 증가 버전이며 UI가 늦은 상태를 버리는 데 사용한다. 이벤트 이력 테이블·토큰별 저장은 만들지 않는다.

| 이벤트 | 의미 |
|---|---|
| `snapshot` | 접속·재접속 시 DB의 최신 상태. 이미 완료됐으면 최종 결과도 포함 |
| `progress` | commit된 단계 변화. 질문 해석, 검증된 검색 조건, 조회 시작·완료 |
| `completed` | 답변과 상태를 함께 commit한 뒤 알림. 답변은 조회 결과·기능 안내·추가 질문 중 하나 |
| `failed` / `cancelled` / `interrupted` | 최종 실패·명시적 취소·서버 중단을 구분. 안전한 오류 코드와 다음 행동만 표시 |

완료 snapshot 또는 종료 이벤트를 받은 클라이언트는 구독을 닫는다. 다른 연결에서 같은 완료 상태가 반복돼도 메시지를 중복 추가하지 않는다.
구독 시작 시와 이후 변경 탐지 사이에 업데이트가 유실되지 않도록 revision 확인을 사용한다. 구현은 0.25초마다 짧은 DB 상태 확인을 수행한다.
SSE 서버가 알림을 놓치더라도 DB snapshot으로 수렴한다. 구독 GET은 모델을 실행하지 않으며 `Last-Event-ID` 기반 이벤트 재생을 약속하지 않는다.

기존 동일 origin Cookie로 GET 구독하므로 브라우저 `EventSource`를 사용할 수 있다. 오류가 나면 일반 fetch 상태 조회로 인증 만료·권한·삭제·일시 끊김을 구분한다.
SSE가 불안정하면 제한된 재연결 또는 상태 polling으로 복원한다. POST 실행 접수를 자동 반복하지 않는다.
[MDN SSE](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events)는 이벤트 구독·프레임을 설명한다. 서버는 [Starlette 스트리밍 응답](https://starlette.dev/responses/) 기반을 검토한다.

## 실행 진행과 연결 복구

| 상황 | 동작 |
|---|---|
| 패널 접기·새로고침·탭 종료 | 실행은 계속. 다시 열면 현재 대화·활성 요청을 조회하고 SSE 구독 |
| SSE 연결 끊김 | 처리 상태를 미확인으로 표시. GET snapshot으로 현재 결과 확인 후 필요하면 재구독 |
| 서버 재시작·실행 task 유실 | 저장 설계의 소유자·deadline 정리로 `INTERRUPTED`. 모델 자동 재실행 없음, 사용자 수동 재시도 |
| 명시적 중지 | request를 취소하고 추가 도구 호출 차단. 이미 실행 중인 원격 추론의 즉시 종료·비용 환불은 보장하지 않음 |
| 전체 삭제 | DB 물리 삭제 완료 후 UI 비움. 진행 task·다른 탭의 늦은 결과는 삭제된 대화에 저장/표시하지 않음 |
| 로그아웃·계정 변경 | 클라이언트 이력·구독만 제거. 저장된 대화는 유지하며 서버 요청은 결과 저장까지 계속 가능. 새 계정에 이전 결과를 표시하지 않음 |

운영자의 프로세스 종료·GPU 전환은 기존 drain 절차에 챗봇 활성 요청을 포함해야 한다. 사용자 화면 종료와 서버 자체 종료를 구분한다.

## 전송·실행 제한

- 1차는 실제 단계와 최종 검증된 답변만 전송한다. 모델 토큰 스트리밍·가짜 진행률·내부 추론 노출은 포함하지 않는다.
- `text/event-stream`·UTF-8·빈 줄 프레임·heartbeat를 준수한다. 자체 parser를 쓰면 청크 분할·여러 data 줄을 검증한다.
- heartbeat는 15초이며 실제 진척을 뜻하지 않는다. CloudFront→ALB→API의 캐시·버퍼링·idle/response timeout을 실제 검증한다.
- 실행 deadline은 60초다. 모델 timeout·repair는 그 안에서 수행하고, SSE 재접속이 실행 deadline을 연장하지 않는다.
- 스트림 시작 전 인증 오류는 기존 HTTP 오류 봉투, 시작 후 오류는 공개 상태로 전달한다. SQL·원문 예외·연락처·프롬프트는 진행 이벤트에 넣지 않는다.
- 조회·상태 갱신은 짧은 트랜잭션으로 수행하고 LLM 응답 대기 중 DB 세션을 붙잡지 않는다. DB 저장 실패 시 정상 완료를 표시하지 않는다.
- 접수 원자성·중복 키, 끊김/완료 경합, 서버 중단, 삭제 후 늦은 저장, 다른 사용자 접근을 통합 검증한다.

## 공개 데이터 형태

- Conversation: UUID `id`, `state_version`, `active_filters`, `active_request`, 생성·변경 시각. 현재 대화 조회는 `{conversation, enabled}`다.
- Request: UUID `id`·`conversation_id`, `status`, `stage`, `revision`, `failure_code`, `search_filters`, `answer`, 생성·완료 시각.
- Message: 정수 `id`·`sequence_no`, `request_id`, `role`, `content`, `result_payload`, 생성 시각. 이력은 `{items, next_cursor}`이며 `before` 순번 이전 페이지를 시간순으로 반환한다.
- Result: `kind`, `text`, `filters`, `items`, `total`, `offset`, `limit=10`, `as_of`, `actions`. 결과 카드는 `id`, `title`, `subtitle`, 표시 필드와 내부 action을 가진다.
- Action은 `open_f2`, `open_property`, `open_buyer`, `open_calendar`만 허용한다. 대상 ID는 상세 조회에서 재검증하며 임의 URL을 실행하지 않는다.
- `reference_message_id`는 같은 대화의 최근 완료 두 답변 중 결과 메시지만 허용한다. 두 번째 이후 결과 페이지에서는 번호 참조 대신 카드의 상세 버튼을 사용한다.
