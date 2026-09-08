---
status: 구현됨
updated: 2026-09-08
---

# F4 챗봇 Backend 구조와 검증

기능 범위와 HTTP·저장 계약은 [요구사항](../../../../docs/requirements/chatbot/overview-and-scope.md),
[AI–Backend 공개 계약](../../project-wiki/references/contracts/chatbot-ai.md),
[실행 구조](../../../../docs/architecture/chatbot/runtime.md),
[API·SSE](../../../../docs/architecture/chatbot/api-and-stream.md),
[저장 설계](../../../../docs/architecture/chatbot/persistence.md)가 정본이다.
PR #100에는 read adapter·인증·DB 저장·HTTP/SSE가 구현돼 있으며 화면 통합은 후속 PR #101의 범위다.
이 문서는 Backend 내부 구현과 변경 시 검증할 불변식만 설명한다. 공유 환경 배포 완료를 뜻하지 않는다.

## 구성과 책임

- `api/chatbot.py`는 쿠키 세션·CSRF, 작성자 권한, HTTP DTO와 SSE를 처리한다. 스트림 인증은 짧은
  자체 DB 세션을 사용한다. `get_db_session`의 yield 수명으로 SSE 연결 내내 DB 연결을 유지하지 않는다.
- `domain/chatbot/models.py`와 `repository.py`는 대화·요청·메시지 및 원자적인 상태 전이를 담당한다.
  숫자·날짜 해석은 `normalization.py`, 읽기 전용 장부·일정 투영은 `query.py`에 둔다.
  단순한 전달 계층과 별도 서비스를 만들지 않고 기존 Backend의 기능별 응집 구조를 따른다.
- `manager.py`는 `workflow_factory(brokerage_id)`로 workflow를 주입받고 lifespan에서 시작·종료한다.
  AI에 넘기는 것은 공개 `brokerage_ai.chatbot` DTO와 `ChatReadPort` 구현이며 DB 세션을 넘기지 않는다.
  AI의 workflow v2 조건 근거 검증 통과 후에도 Backend는 정규화·권한·현재 DB 상태를 다시 검사한다.
  계약 재생성용 고정 규칙 메시지는 AI가 소유하며 Backend에서 프롬프트를 조립하지 않는다.
- 앱 조립과 모델 선택은 `main.py`, `chatbot_runtime.py`, `chatbot_model.py`가 담당한다.
  `CHATBOT` capability는 기존 판단용 모델 설정과 분리한다. 모델 선택 명령은 local loopback DB에서만
  실행하며 `--apply`가 없으면 검증만 수행한다.

## 잠금·실행·삭제

질문 접수는 사무소 행을 잠근 뒤 대화 행을 잠근다. 모델 선택 CLI도 사무소 행을 잠근 상태에서 활성
챗봇 요청을 확인하므로 모델 변경 검사와 새 접수가 서로 추월하지 않는다. 완료·취소·전체 삭제·조건
초기화는 대화 행을 먼저 잠근 뒤 요청 상태를 다시 읽는다. 늦은 완료는 최종 상태를 덮어쓰거나 삭제한
대화를 다시 만들 수 없다.

접수 질문과 요청을 함께 commit하고, 최종 답변·검색 조건·완료 상태도 함께 commit한다. 모든 외부 모델
대기 전에 DB 세션을 닫는다. SSE는 최신 DB snapshot과 revision의 증가만 전달하며 이벤트를 재실행하지
않는다. 재접속은 실행 요청을 새로 만들지 않는다.

동시 처리 제한은 단일 API 프로세스의 관리 중 task 수를 기준으로 한다. 다중 인스턴스용 분산 제한기가
아니다. 사용자 취소는 즉시 DB에 반영하고 전체 삭제는 즉시 물리 삭제하지만, 이미 실행 중인 Provider는
응답 또는 실행 deadline까지 기다린다. 클라이언트 취소만으로 원격 추론 자원이 해제되었다고 간주하지
않는다. 검색·참조 재검증 DB 스레드는 취소 시에도 종료를 기다리며 두 경로 모두 5초 statement timeout을
적용한다. 서버 종료는 중단 상태를 기록하고 task를 정리한다. 유실된 heartbeat·deadline은 중단으로
분류하며 자동 재실행하지 않는다.

## 조회의 의미와 제한

- 매물은 기존 매물장의 세대별 최신 접수 매물을 먼저 선택한 후 조건을 적용한다. 과거의 더 싼 접수
  건이 검색 조건을 만족한다는 이유로 현재 매물을 대체하지 않는다.
- 단지 이름은 정확히 일치하는 이름을 우선한다. 부분 이름이 여러 단지에 맞으면 더 구체적인 이름을
  요청한다. 사용자 입력의 `%`·`_`는 SQL wildcard로 해석하지 않는다.
- 구입장의 거래 유형 저장값은 `매수`·`전세`·`월세`다. AI의 `SALE`·`JEONSE`·`RENT`를 이 값으로
  변환한다. 구입장 희망 면적에는 전용·공급 기준이 저장되어 있지 않아 면적 조회는 안내로 종료한다.
- 구입장 예산은 저장된 희망 범위와 검색 범위의 겹침이다. 양쪽 금액이 모두 NULL인 의뢰를 포함하지
  않으며 한쪽만 있으면 확인된 금액만으로 겹침을 판단한다. 미입력 경계를 무한대나 0으로 추정하지 않는다.
- 일정은 기존 Time Keeper union을 재사용한다. 사용자 지정 기간과 종류를 집계·페이지 제한 전에
  적용하고 종류별 3건 제한을 사용하지 않는다. 최신 `AgendaWindow`의 명시적 필드로 기간을 전달하며
  기존 Time Keeper 화면의 기본 조회 규칙은 바꾸지 않는다. 제거된 `LISTING_RECONTACT`·
  `CLIENT_RECONTACT`는 최초·후속 조회, 저장된 페이지 조건과 과거 장부 결과 참조에서 안내로
  종료한다. 사용자 캘린더의 자유 종류 문자열이 같은 경우에는 정상 캘린더로 취급한다.
- 총건수와 결과 페이지는 하나의 `REPEATABLE READ` snapshot에서 조회한다. 다음 페이지는 저장된
  조건으로 다시 조회하며 기준 시각을 갱신한다. 모델에 인물·연락처·상담 원문을 보내지 않는다.
- 직전 완료된 질문·답변 2쌍만 문맥에 사용한다. 순번 참조는 그 범위에 포함된 저장 메시지의 첫 페이지
  결과만 허용하며 대상이 같은 사무소에 여전히 존재하는지 다시 확인한다.

## 스키마와 검증

`docs/db/migrate/019_CREATE_CHATBOT.sql`은 작성자별 대화 UNIQUE, 대화별 활성 요청 부분 UNIQUE,
중복 접수 키, 메시지 순서·역할 UNIQUE와 사무소·대화 범위를 결속한 복합 FK를 소유한다.
`SQLModel.metadata.create_all()`은 이 제약을 검증하는 대체 수단이 아니다. 실제 PostgreSQL에서 전진
SQL을 적용해 검증한다.

`tests/integration/test_chatbot.py`는 폐기 가능한 별도 schema에 전체 migration을 적용하여 소유권,
중복·경합·물리 삭제, 문맥·이력, 실제 쿠키·CSRF·SSE, Provider·DB 슬롯, deadline·서버 중단,
수치·일정 조회와 참조 조회 timeout을 검사한다. `test_chatbot_model.py`는 실제 DB에서 모델 선택의
기존 판단 설정·업무 데이터 보존, 고정 프로필 불일치 거부, 활성 요청 중 변경 거부와 dry run 무변경을
검사한다. `test_chatbot_failures.py`는 Provider 오류 코드·비밀값 없는 로그, 답변 INSERT 실패의
트랜잭션 rollback과 수동 재시도, 완료·실패 상태를 모두 저장할 수 없을 때 중단 복구를 검사한다.
`TEST_DB_URL`은 로컬 격리 테스트 DB를 가리켜야 한다.

변경 후 저장소 지정 Ruff 검사·포맷과 Backend Pyright·관련 pytest를 실행한다. 실제 모델·HTTP 성능
평가는 단위·통합 테스트와 구분하여 기록하며, 평가 명령·환경 설정은 Backend README와 평가 문서에서
확인한다. Qwen 실제 평가는 사용자 요청으로 보류되었으며 합격한 것으로 표기하지 않는다.

기록된 Luna 모델 측정값은 workflow v2 보완 이전 실행이다. 병합 후 fake·DB 회귀 검사는 변경된
계약과 저장 경로의 검증이며, 새 실제 모델 호출 없이 수정 후 모델 정확도·성능을 통과한 것으로
표시하지 않는다. 원본 평가와 검토 요약의 hash·수치는 유지한다.
