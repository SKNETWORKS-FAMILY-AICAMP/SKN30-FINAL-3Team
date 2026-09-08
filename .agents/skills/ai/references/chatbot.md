---
status: 구현됨
updated: 2026-09-08
---

# F4 챗봇 내부 실행과 평가

구현된 공개 DTO·실행·read capability 계약은 [공통 계약](../../project-wiki/references/contracts/chatbot-ai.md)이
정본이다. PR #100에 구현된 저장·HTTP/SSE 연결은 [챗봇 실행 구조](../../../../docs/architecture/chatbot/runtime.md)에서 관리한다. AI 구현은 `brokerage_ai.chatbot`의 선형 workflow이며 LangGraph·DB·HTTP를 추가하지 않는다.

- 모델은 제한된 의도·원문 조건만 생성한다. AI가 모든 비어 있지 않은 생성 조건의 도구별 허용
  범위·원문 또는 한국어 enum 근거·같은 도구의 refine 상속을 검사한 뒤 read port를 호출한다.
  상세 규칙은 [공통 계약](../../project-wiki/references/contracts/chatbot-ai.md#생성-조건의-근거-검증)을 따른다. Backend도 실제 지원 조건과 권한을 다시 검증한다.
- 질문 하나는 모델 생성 최대 3회와 주 조회 1회, 전체 60초 안에서 처리한다. 전송 오류는 재생성하지
  않으며 계약 오류의 고정 규칙만 되먹인다. 최종 답변은 검증된 Backend 결과 또는 고정 안내다.
- 8K 문맥에서 UTF-8 byte 보수 상한, JSON Schema, 메시지 여유와 출력 1,024 token을 합산한다.
  초과 문맥을 조용히 자르지 않는다. Provider가 보고한 실제 출력·총 토큰도 검사한다.
- 문맥은 현재 조건과 Backend가 선정한 완료 2쌍의 최소 요약이다. 결과 행·대상 ID는 모델에 보내지
  않는다. 직전 명확화에 대한 답변은 해당 질문의 표현을 복원할 수 있다.
- 이전 unsupported 질문과 차단 패턴은 후속 프롬프트에서 제외한다. 연락처·이메일 등 보조 마스킹은
  개인정보 전송 승인을 대신하지 않는다. Backend의 최소 입력 구성과 합성 환경 경계를 유지한다.
- OpenAI Luna에는 미지원 `temperature`를 보내지 않는다. self-hosted에는 0을 사용한다. 모델과
  capability route는 호출자가 명시하며 자동 fallback은 없다.

평가 절차와 실제 실행 근거는 [AI 평가 README](../../../../ai/eval/chatbot/README.md) 및 그 결과 링크를
읽는다. 모델 해석 평가와 DB/API/브라우저 평가의 범위를 섞지 않는다. 이 PR의 평가 기록에서
Qwen은 당시 사용자 지시에 따른 NOT_RUN이며 endpoint 기동이나 GPU 생성은 평가기의 책임이 아니다.

PR #99의 조건 검증 보완은 `chatbot-workflow:v2`에 도입됐고, 현재 v3에도 유지된다.
현재 평가기는 `chatbot-intent-scorer:v2`다. `recent`도 명시된 조건으로 비교하므로 사용자가
최근 정렬을 요청했는데 누락하거나 요청하지 않은 최근 정렬을 덧붙이면 오답이다. 기본 정렬이라는
이유로 비교에서 지우지 않으며, refine은 현재 조건을 병합한 결과를 비교한다.

기존 검토 요약과 원본 hash·점수는 당시 실행의 기록으로 보존한다. 이번 조건 검증·평가기 보완과
단위 테스트 통과는 수정 후 실제 모델을 재평가했다는 근거가 아니다. 기존 요약을 v2 점수나 수정
후 모델 성능으로 다시 표시하지 않으며, 새 모델 평가에는 수정된 workflow와 scorer 버전을
기록한 별도 실행 결과가 필요하다.


`chatbot-workflow:v3`는 계약 오류 재생성 메시지에 고정 `CHATBOT_OUTPUT_CONTRACT` 규칙만
전달한다. 주입 Provider가 던진 계약 오류도 원문·동적 필드 경로·모델 값을 되먹이지 않는다.
초기 프롬프트는 `chatbot-prompt:v1`, 채점기는 v2를 유지한다. 최초 호출 포함 3회 상한과 마지막
예외 타입 보존은 동일하다. 실제 모델 재평가 전에는 과거 측정을 v3 성능으로 해석하지 않는다.
