---
status: 구현됨
updated: 2026-09-08
---

# F4 챗봇 AI–Backend 공개 계약

이 문서는 PR #99의 Python 공개 계약 정본이다. AI facade·DTO·workflow는 구현됐으며,
Backend adapter·인증·DB 저장·HTTP/SSE 연결의 구현 완료를 뜻하지 않는다. 해당 연결은 후속
PR #100·#101의 범위다. [ADR-0006](../decisions/ADR-0006-ai-backend-boundary.md)의 책임 분리를 유지한다.
별도 HTTP API나 새 프레임워크·영속성 결정을 추가하지 않으므로 새 ADR은 만들지 않는다.

## 공개 진입점과 책임

Backend는 [`brokerage_ai.chatbot`](../../../../../ai/src/brokerage_ai/chatbot/__init__.py)에서
DTO·`ChatReadPort`·`ChatbotWorkflow`·공개 오류를 가져온다. 프롬프트와 내부 workflow 함수를
직접 참조하지 않는다. AI에는 SQL·ORM·DB 세션·Repository·FastAPI·LangGraph 객체를 전달하지 않는다.

| 책임 | 소유자 |
|---|---|
| Provider와 ModelRoute 선택·주입, 사용자·사무소 식별 | Backend 조립 지점. Provider 구현은 기존 AI 어댑터 사용 |
| 질문 해석·구조화 출력 검증·문맥 예산·제한된 재생성 | AI |
| 금액·면적·날짜 정규화, 실제 지원 조건·권한·참조 ID 재검증, 정확한 총건수·페이지·결과 계산 | Backend read adapter |
| 요청 실행 수명·취소·저장·복원·HTTP 오류 변환·commit 후 SSE 전달 | Backend |

사무소·사용자 ID는 모델 출력으로 받지 않는다. Backend가 권한 범위를 고정한 adapter를 주입한다.
AI의 조건 해석 성공은 실제 DB 조회 지원이나 권한 검증 완료를 의미하지 않는다.

## DTO

필드·허용값·검증 규칙의 코드 정본은 [`types.py`](../../../../../ai/src/brokerage_ai/chatbot/types.py)다.
DTO는 Pydantic 모델이며 미정의 필드를 거절하고 최상위 필드 재할당을 금지한다.
내부 dict까지 깊은 불변성을 보장하는 것은 아니므로 Backend는 입력과 결과를 다시 검증한다.

| 타입 | 계약 |
|---|---|
| `ChatInput` | `question` 1~2,000자, 현재 `active_filters`, 완료된 `history` 최대 2쌍, 선택적 `reference`, 업무 기준일 `as_of: date` |
| `CompletedTurn` | 질문 최대 2,000자와 Backend가 구성한 종류·총건수 등의 `answer_summary` 최대 200자. 자유 답변 전문·결과 행을 넣지 않음 |
| `ResultReference` | 조회 종류와 표시된 결과 항목 최대 10개. UI의 선택은 권한 근거가 아니며 대상 ID는 read adapter가 다시 확인 |
| `ChatFilters` | 단지·거래 종류·진행 상태, 금액·면적·날짜의 원문 표현, 면적 기준·일정 종류·정렬. 정규화된 SQL 조건이 아님 |
| `ChatIntent` | `tool`, `mode=replace/refine`, `filters`, 선택적 `reference_ordinal` 1~10, `clarification_code` |
| `ChatResult` | 결과 `kind`, 표시 `text`, 검증된 `filters`, 항목 최대 10개, 정확한 `total`, `offset`, 고정 `limit=10`, 조회 시각 `as_of: datetime`, 명시적 UI `actions` |
| `ChatResultItem`·`ChatField`·`ChatAction` | 카드 ID·제목·표시 필드와 허용된 내부 상세/F2 이동 액션. 모델이 임의 URL을 생성하지 않음 |
| `ChatExecution` | `result`, `intent`, 선택적 Provider `diagnostics`, `model_calls` 0~3, `prompt_version`, `workflow_version` |

`tool`은 `properties/buyers/agenda/open_result/help/clarification/unsupported/open_f2`다.
`clarification_code`는 `area_basis/missing_context/ambiguous_condition/unsupported_condition`이며
clarification에만 허용한다. `reference_ordinal`은 open_result에만 허용한다. 비조회 도구의
불확실한 필터는 조회·조건 갱신에 사용하지 않는다. `open_f2`는 이동 버튼만 반환하며 분석을 실행하지 않는다.

## 생성 조건의 근거 검증

조회 의도의 비어 있지 않은 생성 필터는 read capability 호출 전에 모두 검사한다. Schema에
정의된 필드라는 이유만으로 조건을 허용하지 않는다.

- `properties/buyers`는 장부 조건만, `agenda`는 날짜 표현·일정 종류·정렬만 허용한다.
  장부 도구의 날짜 정렬과 agenda의 가격·최근 정렬도 거절한다.
- 단지·진행 상태·금액·면적·날짜 등 원문 문자열은 공백을 제외하고 현재 질문에 있는 표현이어야
  한다. 직전 답변 요약이 `clarification`으로 시작할 때만 그 질문의 표현도 근거에 포함한다.
  더 오래된 질문은 조건 생성의 근거가 아니다.
- 거래 종류·면적 기준·일정 종류·정렬 enum은 해당 값에 대응하는 제한된 한국어 의미 근거를
  검사한다. 예를 들어 `SALE`은 “매매/매수”, `exclusive`는 “전용”, `recent`는 “최근/최신/등록순”
  표현이 필요하다. enum 문자열이 Schema에 있다는 사실이나 모델의 기본값은 근거가 아니다.
- 현재 조건과 같은 값을 상속할 수 있는 경우는 `mode=refine`이며 현재 조건의 `tool`이 생성
  의도의 도구와 같을 때뿐이다. 현재 질문에 명시한 enum 변경은 이전 조건보다 우선하므로
  오래된 값을 유지하거나 다시 생성해 덮어쓰는 출력을 거절한다. 생성 필드가 생략됐더라도
  상속될 기존 값이 현재 질문의 명시적 변경과 충돌하면 거절한다.
- “말고/제외/아닌” 등 지정된 부정 표현이 있는 조회 조건은 명확화가 필요하다. 부정된 단어를
  긍정 enum 근거로 받아 조회하지 않고 계약 재생성에서 명확화를 요구한다. 이 검사는 제한된
  한국어 표현 목록에 기반하므로 일반적인 의미 이해나 모든 바꿔 말하기의 지원을 보장하지 않는다.
- 허용 필드 또는 근거 검사를 어긴 출력은 `ChatbotContractError`로 거절한다. 잘못된 조회
  필터를 조용히 제거해 성공으로 처리하지 않는다. 고정 규칙을 되먹여 같은 모델로 최초 호출
  포함 최대 3회 생성하고, 끝내 실패하면 마지막 계약 오류를 호출자에게 전파한다.

이는 모델이 임의로 조건을 더하는 것을 제한하는 AI 계약이다. 금액·날짜의 의미 정규화와 실제
지원 범위·권한·현재 DB 상태의 검증은 여전히 Backend adapter 책임이다.

## 실행과 read capability

```python
workflow = ChatbotWorkflow(provider=provider, route=route, timeout_seconds=60)
execution = await workflow.run(request, capability=read_adapter, on_progress=publish_stage)

# Backend가 구현·주입하는 Protocol
async def execute(intent: ChatIntent, request: ChatInput) -> ChatResult: ...
```

생성자는 Provider 종류와 route의 일치를 요구하며 timeout은 0초 초과·60초 이하이다.
`run`은 공백·차단·도움말·F2·명확화 경로를 고정 응답으로 처리할 수 있다. 조회가 필요할 때만
`ChatReadPort.execute`를 최대 1회 호출한다. 금액·면적·날짜 의미와 저장 조건은 adapter가
검증하고, 미지원·모호함은 `ChatResult` 안내로 반환할 수 있다. 숫자·카드·답변은 검증된 결과를 사용한다.

한 질문은 주 조회 도구 1종, adapter 내부 보조 조회 포함 최대 3회라는 설계 상한을 따른다.
AI가 검사하는 것은 port 호출 1회이며 adapter 내부 DB 조회 횟수·timeout은 Backend의 책임이다.
`replace/refine` 조건 병합, 과거 참조 재조회와 실제 지원 여부도 Backend에서 검증한다.

`ProgressCallback`은 `async callback(stage)`이며 stage는 `interpreting/searching`뿐이다.
선택적 callback은 await되고 전체 deadline 안에 포함된다. 완료 상태나 SSE 이벤트가 아니며,
Backend가 저장 후 전달해야 한다. 프롬프트·내부 추론·개인정보·가짜 진행률을 실어 보내지 않는다.

`run`은 전체 실행에 비동기 deadline을 적용한다. `interpret(request)`는 합성 모델 평가용
진입점으로 의도·진단·호출 수를 반환한다. read capability·권한 검증·`run`의 전체 timeout을
제공하지 않으므로 Backend의 업무 조회 실행 경로로 대신 사용하지 않는다.

## 제한·오류·문맥

- 문맥은 현재 조건과 Backend가 선택한 완료 2쌍이다. 실패·취소·중단 이력 선정 제외는 Backend 책임이다.
  모델에는 참조 종류·개수만 보내며 결과 행·대상 ID·연락처를 보내지 않는다. 보조 마스킹은
  [외부 전송 정책](../privacy/policy.md)을 대신하지 않는다.
- 8K 문맥과 출력 1,024 token을 예산화하고 초과 입력을 조용히 자르지 않는다. 상한 초과는
  `ChatbotContextLimitError`다. Provider가 사용량을 보고하면 실제 총량·출력량도 검사한다.
- 구조화 출력·생성 조건 근거 등 계약 위반만 동일 모델로 최초 호출 포함 최대 3회 생성한다. 마지막 실패는
  `ChatbotContractError`, Provider의 `ProviderOutputInvalidError` 또는 Pydantic `ValidationError`로 전파된다.
- Provider 전송·rate-limit 오류와 capability·callback 예외는 호출자에게 전파한다. 모델 자동 fallback은 없다.
  deadline 만료의 `TimeoutError`와 외부 취소의 `CancelledError`도 Backend가 상태·저장 정책으로 처리한다.
- 일반적인 모호·미지원 질문은 예외 대신 안내 결과를 반환한다. 결과가 반환됐다는 이유만으로
  검색 조건이나 참조를 갱신하지 말고 `kind`와 Backend 상태 전이 규칙을 함께 확인한다.

[workflow 코드](../../../../../ai/src/brokerage_ai/chatbot/workflow.py)와
[계약·실행 테스트](../../../../../ai/tests/unit/chatbot/test_workflow.py)가 근거다.
AI 내부 예산·프롬프트·평가 절차는 [AI 모듈 문서](../../../ai/references/chatbot.md),
전체 저장·HTTP/SSE 설계는 [실행 구조](../../../../../docs/architecture/chatbot/runtime.md)에서 관리한다.
