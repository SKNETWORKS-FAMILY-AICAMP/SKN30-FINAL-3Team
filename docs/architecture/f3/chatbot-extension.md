---
status: 제안
updated: 2026-09-09
---

# F3 확장의 챗봇 후속 연계 검토

기준 dev `5950681`. 챗봇 확장 검토 서브에이전트가 문서·코드를 읽기 전용으로 조사하고 메인 기획에 반영했다.
결론은 **공통 Backend 조회·접수 유스케이스를 준비하면 연계 가능하나, 도구 등록만으로 완성되지는 않는다**이다.
이번 [F3 기능 범위](../../requirements/f3/judgment-results-list.md)는 챗봇 도구 활성화까지 포함하지 않는다.

## 기존 결정과 후속 문서의 구분

모든 모듈 `references/decisions/ADR-*.md` 조사에서 챗봇 F3 연계를 직접 승인한 전용 ADR은 확인되지 않았다.
사용자가 언급한 후속 계획은 다음 요구사항·아키텍처 문서에 있다. 기존 ADR의 내용을 추정해 새 결정으로 표현하지 않는다.

| 근거 | 현재 의미 |
|---|---|
| [챗봇 범위](../../requirements/chatbot/overview-and-scope.md) | F3 실행·판정·성사 가능성 설명은 보류. 현재 도구 미등록, 해당 요청은 보류 안내와 실행 API 0회가 수용 기준 |
| [챗봇 개요의 확장](../chatbot/overview.md) | 도구·Backend capability·카드·평가 사례를 함께 추가. F3는 별도 실행 adapter와 기존 실행 상태 재사용 |
| [챗봇 저장 설계](../chatbot/persistence.md) | chat request와 agent_run 연결은 후속 검토. 대화 삭제로 F3 감사 이력 cascade 삭제 금지 |
| [ADR-0006](../../../.agents/skills/project-wiki/references/decisions/ADR-0006-ai-backend-boundary.md) | Backend가 권한·DB·실행을 소유하고 AI에는 공개 DTO·capability만 전달 |
| [ADR-0035](../../../.agents/skills/project-wiki/references/decisions/ADR-0035-f3-conditional-automation-results.md) | 사용자 1차 구현 요청으로 ADR-0018을 부분 대체. 조건부 자동 판정·완료 재사용·저장 결과 GET 구현, 챗봇 도구는 후속 |

## 이번에 준비할 최소 경계

[API·내부 기능 정의](expansion-contracts.md)의 조회 함수(`judgment_queries`)와 접수 함수(`service.queue_cross_judgment_run`)를 HTTP와 무관한 Backend 유스케이스로 구현했다.
화면·자동 이벤트·후속 챗봇이 같은 입력 검증·최신성·공개 정책·실행 재사용을 거치게 한다.

| 공통 기능 | F3 화면의 진입 | 후속 챗봇 연결 제안 |
|---|---|---|
| 결과 목록 | 신규 GET 목록 | 제한 조회 capability `list_f3_results` |
| 대상 최신/과거 결과 | 신규 GET 대상·결과 상세 | `get_f3_result`와 공통 상세 이동 action |
| 필요한 분석 접수 | 기존 POST /runs 확장 | 명시적 실행 의도에만 별도 command adapter. 인증된 요청자·사무소 고정 |
| 진행 확인 | 기존 GET /runs/{id} | 접수 확인·run ID·결과 화면 링크를 반환하고 챗 응답 완료 |

위 도구명은 후속 제안이다. Backend 내부에서 자신의 HTTP API를 호출하거나 챗봇 전용 F3 후보 검색·판정 workflow를 복제하지 않는다.
이번에는 범용 registry·공통 packages·새 microservice·챗-F3 연결 테이블을 미리 만들지 않는다.

## 후속 구현에서 실제 바꿔야 할 곳

- [ChatLookup](../../../backend/src/domain/chatbot/query.py)는 현재 허용 조회 DTO를 검증한다. 새 command adapter는 세션의 `requested_by`까지 주입하고 대화 소유권·현재 상태를 검사해야 한다.
- [ChatTool/Action 타입](../../../ai/src/brokerage_ai/chatbot/types.py)은 명시적 allowlist다. F3 도구·결과·참조·이동 DTO와 Backend 검증·Frontend decoder/action handler를 함께 확장한다.
- [챗봇 workflow](../../../ai/src/brokerage_ai/chatbot/workflow.py)는 F3 요청을 모델 호출 전 unsupported 처리한다. 후속 범위 합의 후 정책·프롬프트·평가 사례까지 함께 바꿔야 한다.
- [F3 접수](../../../backend/src/domain/agent_execution/service.py)와 [결과 조회](../../../backend/src/domain/agent_execution/results.py)는 재사용 기반이다. 현재는 전체 입력 identity 검증과 완료 실행 재사용을 구현했으며 새 조회는 `judgment_queries.py`를 사용한다.
- 화면 이동은 [F3 화면 명세](../../screen/f3-judgment-results.md)의 typed navigation을 공유한다. 자연어 ID를 그대로 실행하지 않고 Backend가 대상과 권한을 확정한다.

## 수명주기·권한·모델 제약

1. **조회는 실행하지 않는다.** 결과가 없다는 이유로 채팅 조회가 판정을 접수하지 않는다. 구체적인 갱신 요청/버튼은 실행 의도로 처리하고 모호한 대상은 먼저 선택한다. HTTP·채팅 재전송은 동일 실행을 재사용한다.
2. **챗 요청과 F3 작업의 수명은 다르다.** [챗 API](../chatbot/api-and-stream.md)의 60초 deadline 안에서 F3 완료를 계속 기다리지 않는다. 최신 결과는 즉시 읽고 필요한 작업은 접수 확인 후 응답을 끝낸다. Worker는 독립적으로 지속하며 SSE 재연결이 F3를 재접수하지 않는다.
3. **개인 대화와 사무소 공유 판정을 구분한다.** 대화는 사무소+작성자 소유이고 F3는 사무소 공유다. 사무소/요청자 ID는 모델 인자에서 받지 않는다. 과거 답변을 다시 열 때도 대상·결과·근거의 존재와 현재 권한을 검사한다.
4. **대화 삭제·취소는 공유 F3 작업을 취소하지 않는다.** 챗 처리/구독만 종료한다. 후속 연결을 만들 때 접수와 대화 삭제 경합의 transaction 경계를 정하고 늦은 callback이 대화를 재생성하지 못하게 한다. F3 결과 보존은 F3 정책을 따른다.
5. **공개 가능성과 최신성은 공통 유스케이스를 따른다.** 기존 결과의 합성 표식/유효 카드 검사를 목록·채팅 집계가 우회하지 않는다. 공개 불가와 정상 후보 0건을 구분하며 이전 판정을 최신 추천으로 요약하지 않는다.
6. **챗 모델이 새 F3 판정을 만들지 않는다.** 저장된 등급·근거를 전달하며 새 성사 확률·등급을 생성하지 않는다. 일반 장부 조회와 카드 추정 조건 기반 후보 검색은 의미가 다르다. CHATBOT·POSITION_CARD·BROKERAGE_JUDGMENT 설정도 각각 유지한다.
7. **general GPU의 전체 처리량을 관리한다.** 현재 챗 동시 실행 제한은 Worker 후보 병렬 호출을 제한하지 않는다. 상시 임대료와 별개로 자동 작업이 대화형 요청을 밀어내지 않도록 역할별 우선순위·전체 동시성 예산을 적용한다. 프로세스 내부 semaphore만으로 다중 host 제한을 보장하지 않는다.

## 활성화 순서와 검증

F3의 저장 조회·자동 갱신을 먼저 완성하고, 후속에는 챗 조회/화면 이동 → 명시적 갱신 접수 순으로 연계한다.
기존 F3 unsupported 수용 기준은 해당 후속 변경에서 함께 개정한다. 이번 기획이 이를 폐기하지 않는다.

후속 검증에는 다른 사무소/작성자 접근, 삭제·취소·접수 경합, 공개 차단·stale, 60초 초과 F3의 독립 지속,
SSE 재연결 재접수 0회, 자동/화면/챗 동시 접수 중복 방지, 도구 활성화 후 프롬프트 주입 회귀와 모델 설정 독립성을 포함한다.
구현·실제 챗 모델 평가·공유 GPU 부하 검증은 이번에 수행하지 않았다.
